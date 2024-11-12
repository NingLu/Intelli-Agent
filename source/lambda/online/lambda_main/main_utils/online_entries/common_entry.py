import traceback
import json 
import uuid 
import re
from typing import Annotated, Any, TypedDict, List,Union

from common_logic.common_utils.chatbot_utils import ChatbotManager
from common_logic.common_utils.constant import (
    IndexType,
    LLMTaskType,
    SceneType,
    GUIDE_INTENTION_NOT_FOUND,
    GUIDE_INTENTION_NOT_FOUND,
    Threshold,
)
from common_logic.common_utils.lambda_invoke_utils import (
    is_running_local,
    node_monitor_wrapper,
    send_trace,
)
from langchain_core.messages import ToolMessage,AIMessage
from common_logic.common_utils.logger_utils import get_logger
from common_logic.common_utils.prompt_utils import get_prompt_templates_from_ddb
from common_logic.common_utils.python_utils import add_messages, update_nest_dict
from common_logic.common_utils.response_utils import process_response
from common_logic.langchain_integration.tools import ToolManager
from langchain_core.tools import BaseTool
from langchain_core.messages.tool import ToolCall
from langgraph.prebuilt.tool_node import ToolNode,TOOL_CALL_ERROR_TEMPLATE
from common_logic.langchain_integration.chains import LLMChain
from common_logic.common_utils.serialization_utils import JSONEncoder
from common_logic.common_utils.monitor_utils import format_intention_output, format_preprocess_output, format_qq_data
from common_logic.common_utils.ddb_utils import custom_index_desc
from lambda_main.main_utils.parse_config import CommonConfigParser
from langgraph.graph import END, StateGraph
from common_logic.langchain_integration.retrievers.retriever import lambda_handler as retrieve_fn
from common_logic.common_utils.monitor_utils import (
    format_preprocess_output,
    format_qq_data,
    format_intention_output
)
from lambda_intention_detection.intention import get_intention_results
from lambda_query_preprocess.query_preprocess import conversation_query_rewrite
from common_logic.langchain_integration.chains import LLMChain
from common_logic.common_utils.serialization_utils import JSONEncoder


logger = get_logger("common_entry")



class ChatbotState(TypedDict):
    ########### input/output states ###########
    # inputs
    # origin event body
    event_body: dict
    # origianl input question
    query: str
    # chat history between human and agent
    chat_history: Annotated[list[dict], add_messages]
    # complete chatbot config, consumed by all the nodes
    chatbot_config: dict
    # websocket connection id for the agent
    ws_connection_id: str
    # whether to enbale stream output via ws_connection_id
    stream: bool
    # message id related to original input question
    message_id: str = None
    # record running states of different nodes
    trace_infos: Annotated[list[str], add_messages]
    # whether to enbale trace info update via streaming ouput
    enable_trace: bool
    # outputs
    # final answer generated by whole app graph
    answer: Any
    # information needed return to user, e.g. intention, context, figure and so on, anything you can get during execution
    extra_response: Annotated[dict, update_nest_dict]
    # addition kwargs which need to save into ddb
    ddb_additional_kwargs: dict
    # response of entire app
    app_response: Any

    ########### query rewrite states ###########
    # query rewrite results
    query_rewrite: str = None

    ########### intention detection states ###########
    # intention type of retrieved intention samples in search engine, e.g. OpenSearch
    intent_type: str = None
    # retrieved intention samples in search engine, e.g. OpenSearch
    intent_fewshot_examples: list
    # tools of retrieved intention samples in search engine, e.g. OpenSearch
    intent_fewshot_tools: list
    all_knowledge_retrieved_list: list

    ########### retriever states ###########
    # contexts information retrieved in search engine, e.g. OpenSearch
    qq_match_results: list = []
    qq_match_contexts: dict
    contexts: str = None
    figure: list = None

    ########### agent states ###########
    # current output of agent
    # agent_current_output: dict
    # # record messages during agent tool choose and calling, including agent message, tool ouput and error messages
    agent_tool_history: Annotated[List[Union[AIMessage,ToolMessage]], add_messages]
    # # the maximum number that agent node can be called
    # agent_repeated_call_limit: int
    # # the current call time of agent
    # agent_current_call_number: int  #
    # # whehter the current call time is less than maximum number of agent call
    # agent_repeated_call_validation: bool
    # # function calling
    # # whether the output of agent can be parsed as the valid tool calling
    # function_calling_parse_ok: bool
    # # whether the current parsed tool calling is run once
    exit_tool_calling: bool
    # # current tool calls
    # function_calling_parsed_tool_calls: list
    # current_agent_tools_def: list
    last_tool_messages: List[ToolMessage]
    tools: List[BaseTool]
    # the global rag tool use all knowledge
    all_knowledge_rag_tool: BaseTool


####################
# nodes in graph #
####################


@node_monitor_wrapper
def query_preprocess(state: ChatbotState):

    # output: str = invoke_lambda(
    #     event_body=state,
    #     lambda_name="Online_Query_Preprocess",
    #     lambda_module_path="lambda_query_preprocess.query_preprocess",
    #     handler_name="lambda_handler",
    # )

    
    query_rewrite_llm_type = state.get("query_rewrite_llm_type",None) or LLMTaskType.CONVERSATION_SUMMARY_TYPE
    output = conversation_query_rewrite(
        query=state['query'],
        chat_history=state['chat_history'],
        message_id=state['message_id'],
        trace_infos=state['trace_infos'],
        chatbot_config=state['chatbot_config'],
        query_rewrite_llm_type=query_rewrite_llm_type
    )

    preprocess_md = format_preprocess_output(state["query"], output)
    send_trace(f"{preprocess_md}")
    return {"query_rewrite": output}


@node_monitor_wrapper
def intention_detection(state: ChatbotState):
    retriever_params = state["chatbot_config"]["qq_match_config"]
    retriever_params["query"] = state[
        retriever_params.get("retriever_config", {}).get("query_key", "query")
    ]
   
    output = retrieve_fn(retriever_params)
    context_list = []
    qq_match_contexts = []
    qq_match_threshold = retriever_params["threshold"]
    for doc in output["result"]["docs"]:
        if doc["retrieval_score"] > qq_match_threshold:
            doc_md = format_qq_data(doc)
            send_trace(
                f"\n\n**similar query found**\n\n{doc_md}",
                state["stream"],
                state["ws_connection_id"],
                state["enable_trace"],
            )
            query_content = doc["answer"]
            # query_content = doc['answer']['jsonlAnswer']
            return {
                "answer": query_content,
                "intent_type": "similar query found",
            }

        if doc["retrieval_score"] > Threshold.QQ_IN_RAG_CONTEXT:
            question = doc["question"]
            answer = doc["answer"]
            context_list.append(f"问题: {question}, \n答案：{answer}")
            qq_match_contexts.append(doc)

    if state["chatbot_config"]["agent_config"]["only_use_rag_tool"]:
        return {"qq_match_results": context_list, "intent_type": "intention detected"}

    # get intention results from aos
    intention_config = state["chatbot_config"].get("intention_config",{})
    query_key = intention_config.get("retriever_config",{}).get("query_key","query")
    query = state[query_key]
    intent_fewshot_examples, intention_ready = get_intention_results(
        query,
        {
            **intention_config,
        }
    )

    intent_fewshot_tools: list[str] = list(
        set([e["intent"] for e in intent_fewshot_examples])
    )
    all_knowledge_retrieved_list = []
    markdown_table = format_intention_output(intent_fewshot_examples)

    group_name = state["chatbot_config"]["group_name"]
    chatbot_id = state["chatbot_config"]["chatbot_id"]
    custom_qd_index = custom_index_desc(group_name, chatbot_id)
    

    # TODO need to modify with new intent logic
    # if not intention_ready and not custom_qd_index:
    if not intention_ready:
        # retrieve all knowledge
        retriever_params = state["chatbot_config"]["private_knowledge_config"]
        retriever_params["query"] = state[
            retriever_params.get("retriever_config", {}).get("query_key", "query")
        ]
        threshold = Threshold.INTENTION_ALL_KNOWLEDGAE_RETRIEVE
        output = retrieve_fn(retriever_params)

        info_to_log = []
        all_knowledge_retrieved_list = []
        for doc in output["result"]["docs"]:
            if doc['score'] >= threshold:
                all_knowledge_retrieved_list.append(doc["page_content"])
            info_to_log.append(f"score: {doc['score']}, page_content: {doc['page_content'][:200]}")

        send_trace(
            f"all knowledge retrieved:\n {'\n'.join(info_to_log)}",
            state["stream"],
            state["ws_connection_id"],
            state["enable_trace"],
        )
    # elif not intention_ready and custom_qd_index:
    #     intent_fewshot_examples = []
    #     intent_fewshot_tools: list[str] = []
    # else:
    send_trace(
        f"{markdown_table}",
        state["stream"],
        state["ws_connection_id"],
        state["enable_trace"],
    )
    
    # rename tool name
    intent_fewshot_tools = [tool_rename(i) for i in intent_fewshot_tools]
    intent_fewshot_examples = [
        {**e, "intent": tool_rename(e["intent"])} for e in intent_fewshot_examples
    ]

    return {
        "intent_fewshot_examples": intent_fewshot_examples,
        "intent_fewshot_tools": intent_fewshot_tools,
        "all_knowledge_retrieved_list": all_knowledge_retrieved_list,
        "qq_match_results": context_list,
        "qq_match_contexts": qq_match_contexts,
        "intent_type": "intention detected"
    }

@node_monitor_wrapper
def agent(state: ChatbotState):
    # two cases to invoke rag function
    # 1. when valid intention fewshot found
    # 2. for the first time, agent decides to give final results
    # deal with once tool calling
    last_tool_messages = state["last_tool_messages"]
    if last_tool_messages and len(last_tool_messages) == 1:
        last_tool_message = last_tool_messages[0]
        tool:BaseTool = ToolManager.get_tool(
            scene=SceneType.COMMON,
            name=last_tool_message.name
        )
        if tool.return_direct:
            send_trace("once tool", enable_trace=state["enable_trace"])
            if tool.response_format == "content_and_artifact":
                content = last_tool_message.artifact
            else:
                content = last_tool_message.content
            return {"answer": content, "exit_tool_calling": True}

    no_intention_condition = not state["intent_fewshot_examples"]

    if (
        # no_intention_condition,
        # or first_tool_final_response
        state["chatbot_config"]["agent_config"]["only_use_rag_tool"]
    ):
        if state["chatbot_config"]["agent_config"]["only_use_rag_tool"]:
            send_trace("agent only use rag tool",
                       enable_trace=state["enable_trace"])
        elif no_intention_condition:
            send_trace(
                "no_intention_condition, switch to rag tool",
                enable_trace=state["enable_trace"],
            )
         
        all_knowledge_rag_tool = state['all_knowledge_rag_tool']
        agent_message = AIMessage(content="",tool_calls=[
            ToolCall(
                id=uuid.uuid4().hex,
                name=all_knowledge_rag_tool.name,
                args={"query":state["query"]}
            )
        ])
        tools = [
            ToolManager.get_tool(
                scene=SceneType.COMMON,
                name=all_knowledge_rag_tool.name
                )
            ]
        return {"agent_tool_history":[agent_message],"tools":tools}

    # normal call
    agent_config = state["chatbot_config"]['agent_config']

    tools_name = list(set(state['intent_fewshot_tools'] + agent_config['tools']))
    # get tools from tool names
    tools = [
        ToolManager.get_tool(
            scene=SceneType.COMMON,
            name=name
            ) 
        for name in tools_name
    ]
    llm_config = {
        **agent_config['llm_config'],
        "tools": tools,
        "fewshot_examples": state['intent_fewshot_examples'],
        "all_knowledge_retrieved_list":state['all_knowledge_retrieved_list']
    }
    group_name = state['chatbot_config']['group_name']
    chatbot_id = state['chatbot_config']['chatbot_id']
    prompt_templates_from_ddb = get_prompt_templates_from_ddb(
        group_name,
        model_id = llm_config['model_id'],
        task_type=LLMTaskType.TOOL_CALLING_API,
        chatbot_id=chatbot_id
    )
    llm_config.update(**prompt_templates_from_ddb)

    tool_calling_chain = LLMChain.get_chain(
        intent_type=LLMTaskType.TOOL_CALLING_API,
        scene=SceneType.COMMON,
        **llm_config
    )
    
    agent_message:AIMessage = tool_calling_chain.invoke({
        "query":state['query'],
        "chat_history":state['chat_history'],
        "agent_tool_history":state['agent_tool_history']
    })

    send_trace(
        f"\n\n**agent_current_output:** \n{agent_message}\n\n",
        state["stream"],
        state["ws_connection_id"]
    )
    if not agent_message.tool_calls:
        return {"answer": agent_message.content, "exit_tool_calling": True}

    return {"agent_tool_history":[agent_message],"tools":tools}


@node_monitor_wrapper
def llm_direct_results_generation(state: ChatbotState):
    group_name = state["chatbot_config"]["group_name"]
    llm_config = state["chatbot_config"]["chat_config"]
    task_type = LLMTaskType.CHAT

    prompt_templates_from_ddb = get_prompt_templates_from_ddb(
        group_name, model_id=llm_config["model_id"], task_type=task_type
    )
    logger.info(prompt_templates_from_ddb)

    llm_config = {
                **llm_config,
                "stream": state["stream"],
                "intent_type": task_type,
                **prompt_templates_from_ddb,
            }

    llm_input = {
                "query": state["query"],
                "chat_history": state["chat_history"],
            }
    
    chain = LLMChain.get_chain(
        **llm_config
    )
    answer = chain.invoke(llm_input)

    return {"answer": answer}


@node_monitor_wrapper
def tool_execution(state):
    """executor lambda
    Args:
        state (NestUpdateState): _description_

    Returns:
        _type_: _description_
    """
    tools:List[BaseTool] = state['tools']

    def handle_tool_errors(e):
        content = TOOL_CALL_ERROR_TEMPLATE.format(error=repr(e))
        logger.error(f"Tool execution error:\n{traceback.format_exc()}")
        return content

    tool_node = ToolNode(
        tools,
        handle_tool_errors=handle_tool_errors
    )
    last_agent_message:AIMessage = state["agent_tool_history"][-1]

    tool_calls = last_agent_message.tool_calls

    tool_messages:List[ToolMessage] = tool_node.invoke(
        [AIMessage(content="",tool_calls=tool_calls)]
    )

    send_trace(f'**tool_execute_res:** \n{tool_messages}', enable_trace=state["enable_trace"])
    return {
            "agent_tool_history": tool_messages,
            "last_tool_messages": tool_messages
        }


def final_results_preparation(state: ChatbotState):
    answer = state['answer']
    if isinstance(answer,str):
        answer = re.sub("<thinking>.*?</thinking>","",answer,flags=re.S).strip()
        state['answer'] = answer
    app_response = process_response(state["event_body"], state)
    return {"app_response": app_response}


def matched_query_return(state: ChatbotState):
    return {"answer": state["answer"]}


def intention_not_ready(state: ChatbotState):
    return {"answer": state["answer"]}


################
# define edges #
################


def query_route(state: dict):
    return f"{state['chatbot_config']['chatbot_mode']} mode"


def intent_route(state: dict):
    return state["intent_type"]


def agent_route(state: dict):
    if state.get("exit_tool_calling", False):
        return "no need tool calling"
    # state["agent_repeated_call_validation"] = (
    #     state["agent_current_call_number"] < state["agent_repeated_call_limit"]
    # )
    # if state["agent_repeated_call_validation"]:

    return "valid tool calling"
    # else:
    #     # TODO give final strategy
    #     raise RuntimeError


#############################
# define online top-level graph for app #
#############################


def build_graph(chatbot_state_cls):
    workflow = StateGraph(chatbot_state_cls)

    # add node for all chat/rag/agent mode
    workflow.add_node("query_preprocess", query_preprocess)
    # chat mode
    workflow.add_node("llm_direct_results_generation",
                      llm_direct_results_generation)
    # rag mode
    # workflow.add_node("knowledge_retrieve", knowledge_retrieve)
    # workflow.add_node("llm_rag_results_generation", llm_rag_results_generation)
    # agent mode
    workflow.add_node("intention_detection", intention_detection)
    workflow.add_node("matched_query_return", matched_query_return)
    workflow.add_node("intention_not_ready", intention_not_ready)
    # agent sub graph
    workflow.add_node("agent", agent)
    workflow.add_node("tools_execution", tool_execution)
    workflow.add_node("final_results_preparation", final_results_preparation)

    # add all edges
    workflow.set_entry_point("query_preprocess")
    # chat mode
    workflow.add_edge("llm_direct_results_generation",
                      "final_results_preparation")
    # rag mode
    # workflow.add_edge("knowledge_retrieve", "llm_rag_results_generation")
    # workflow.add_edge("llm_rag_results_generation", END)
    # agent mode
    workflow.add_edge("tools_execution", "agent")
    workflow.add_edge("matched_query_return", "final_results_preparation")
    workflow.add_edge("intention_not_ready", "final_results_preparation")
    workflow.add_edge("final_results_preparation", END)

    # add conditional edges
    # choose running mode based on user selection:
    # 1. chat mode: let llm generate results directly
    # 2. rag mode: retrive all knowledge and let llm generate results
    # 3. agent mode: let llm generate results based on intention detection, tool calling and retrieved knowledge
    workflow.add_conditional_edges(
        "query_preprocess",
        query_route,
        {
            "chat mode": "llm_direct_results_generation",
            "agent mode": "intention_detection",
        },
    )

    # three running branch will be chosen based on intention detection results:
    # 1. similar query found: if very similar queries were found in knowledge base, these queries will be given as results
    # 2. intention detected: if intention detected, the agent logic will be invoked
    workflow.add_conditional_edges(
        "intention_detection",
        intent_route,
        {
            "similar query found": "matched_query_return",
            "intention detected": "agent",
            "intention not ready": "intention_not_ready",
        },
    )

    # the results of agent planning will be evaluated and decide next step:
    # 1. valid tool calling: the agent chooses the valid tools, and the tools will be executed
    # 2. no need tool calling: the agent thinks no tool needs to be called, the final results can be generated
    workflow.add_conditional_edges(
        "agent",
        agent_route,
        {
            "valid tool calling": "tools_execution",
            "no need tool calling": "final_results_preparation",
        },
    )

    app = workflow.compile()
    return app


#####################################
# define online sub-graph for agent #
#####################################
app = None

def tool_rename(name:str) -> str:
    """
    rename the tool name
    """
    return name.replace("-","_")



def register_rag_tool_from_config(event_body: dict):
    group_name = event_body.get("chatbot_config").get("group_name", "Admin")
    chatbot_id = event_body.get("chatbot_config").get("chatbot_id", "admin")
    chatbot_manager = ChatbotManager.from_environ()
    chatbot = chatbot_manager.get_chatbot(group_name, chatbot_id)
    logger.info(f"chatbot info: {chatbot}")
    registered_tool_names = []
    for index_type, item_dict in chatbot.index_ids.items():
        if index_type != IndexType.INTENTION:
            for index_content in item_dict["value"].values():

                if "indexId" in index_content and "description" in index_content:
                    # Find retriever contain index_id
                    retrievers = event_body["chatbot_config"]["private_knowledge_config"]['retrievers']
                    retriever = None 
                    for retriever in retrievers:
                        if retriever["index_name"] == index_content["indexId"]:
                            break
                    assert retriever is not None,retrievers
                    rerankers = event_body["chatbot_config"]["private_knowledge_config"]['rerankers']
                    if rerankers:
                        rerankers = [rerankers[0]]
                    # index_name = index_content["indexId"]
                    index_name = tool_rename(index_content["indexId"])
                    description = index_content["description"]
                    # TODO give specific retriever config
                    ToolManager.register_common_rag_tool(
                        retriever_config={
                            "retrievers":[retriever],
                            "rerankers":rerankers,
                            "llm_config": event_body["chatbot_config"]["private_knowledge_config"]['llm_config']
                        },
                        name=index_name,
                        scene=SceneType.COMMON,
                        description=description,
                        return_direct=True
                    )
                    registered_tool_names.append(index_name)
                    logger.info(f"registered rag tool: {index_name}, description: {description}")
    return registered_tool_names


def register_custom_lambda_tools_from_config(event_body):
    agent_config_tools = event_body['chatbot_config']['agent_config']['tools']
    new_agent_config_tools = []
    for tool in agent_config_tools:
        if isinstance(tool,str):
            new_agent_config_tools.append(tool)
        elif isinstance(tool, dict):
            tool_name = tool['name']
            assert tool_name not in new_agent_config_tools, f"repeat tool: {tool_name}\n{agent_config_tools}"
            if "lambda_name" in tool:
                ToolManager.register_aws_lambda_as_tool(
                    lambda_name=tool["lambda_name"],
                    tool_def={
                       "description":tool["description"],
                       "properties":tool['properties'],
                       "required":tool.get('required',[])
                    },
                    name=tool_name,
                    scene=SceneType.COMMON,
                    return_direct=tool.get("return_direct",False)
                )
            new_agent_config_tools.append(tool_name)
        else:
            raise ValueError(f"tool type {type(tool)}: {tool} is not supported")
    
    event_body['chatbot_config']['agent_config']['tools'] = new_agent_config_tools
    return new_agent_config_tools


def common_entry(event_body):
    """
    Entry point for the Lambda function.
    :param event_body: The event body for lambda function.
    return: answer(str)
    """
    global app
    if app is None:
        app = build_graph(ChatbotState)

    # debuging
    if is_running_local():
        with open("common_entry_workflow.png", "wb") as f:
            f.write(app.get_graph().draw_mermaid_png())

    ################################################################################
    # prepare inputs and invoke graph
    event_body["chatbot_config"] = CommonConfigParser.from_chatbot_config(
        event_body["chatbot_config"]
    )
    logger.info(event_body)
    chatbot_config = event_body["chatbot_config"]
    query = event_body["query"]
    use_history = chatbot_config["use_history"]
    chat_history = event_body["chat_history"] if use_history else []
    stream = event_body["stream"]
    message_id = event_body["custom_message_id"]
    ws_connection_id = event_body["ws_connection_id"]
    enable_trace = chatbot_config["enable_trace"]
    agent_config = event_body["chatbot_config"]["agent_config"]
    
    # register as rag tool for each aos index
    # print('private_knowledge_config',event_body["chatbot_config"]["private_knowledge_config"])
    registered_tool_names = register_rag_tool_from_config(event_body)
    # update private knowledge tool to agent config
    for registered_tool_name in registered_tool_names:
        if registered_tool_name not in agent_config['tools']:
            agent_config['tools'].append(registered_tool_name)

    # register lambda tools
    register_custom_lambda_tools_from_config(event_body)
    # 
    logger.info(f'event body to graph:\n{json.dumps(event_body,ensure_ascii=False,cls=JSONEncoder)}')

    # define all knowledge rag tool
    all_knowledge_rag_tool = ToolManager.register_common_rag_tool(
                retriever_config=event_body["chatbot_config"]["private_knowledge_config"],
                name="all_knowledge_rag_tool",
                scene=SceneType.COMMON,
                description="all knowledge rag tool",
                return_direct=True
    )

    # invoke graph and get results
    response = app.invoke(
        {
            "event_body": event_body,
            "stream": stream,
            "chatbot_config": chatbot_config,
            "query": query,
            "enable_trace": enable_trace,
            "trace_infos": [],
            "message_id": message_id,
            "chat_history": chat_history,
            "agent_tool_history": [],
            "ws_connection_id": ws_connection_id,
            "debug_infos": {},
            "extra_response": {},
            "qq_match_results": [],
            "last_tool_messages":None,
            "all_knowledge_rag_tool":all_knowledge_rag_tool,
            "tools":None,
            "ddb_additional_kwargs": {}
        },
        config={"recursion_limit": 20}
    )
    # print('extra_response',response['extra_response'])
    return response["app_response"]


main_chain_entry = common_entry
