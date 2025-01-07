/**********************************************************************************************************************
 *  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.                                                *
 *                                                                                                                    *
 *  Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance    *
 *  with the License. A copy of the License is located at                                                             *
 *                                                                                                                    *
 *      http://www.apache.org/licenses/LICENSE-2.0                                                                    *
 *                                                                                                                    *
 *  or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES *
 *  OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions    *
 *  and limitations under the License.                                                                                *
 *********************************************************************************************************************/

import { Aws, Duration, StackProps, NestedStack, Stack, PhysicalName } from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as lambdaEventSources from "aws-cdk-lib/aws-lambda-event-sources";
import { v4 as uuidv4 } from 'uuid';
import * as apigw from "aws-cdk-lib/aws-apigateway";
import { PythonFunction } from "@aws-cdk/aws-lambda-python-alpha";
import { Construct } from "constructs";
import { DynamoDBTable } from "../shared/table";
import { join } from "path";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

import { Constants } from "../shared/constants";
import { LambdaLayers } from "../shared/lambda-layers";
import { IAMHelper } from "../shared/iam-helper";
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { SystemConfig } from "../shared/types";
import { SharedConstruct, SharedConstructOutputs } from "../shared/shared-construct";
import { LambdaFunction } from "../shared/lambda-helper";
import { Runtime, Code, Function, Architecture } from "aws-cdk-lib/aws-lambda";
import { ApiConstructOutputs } from "../api/api-stack";
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { WSWebSocketConstruct } from "./websocket-api";
import { QueueConstruct } from "../chat/chat-queue";
import { PortalConstruct } from "../ui/ui-portal";
import { UserConstruct } from "../user/user-construct";



interface WorkspaceProps extends StackProps {
  readonly config: SystemConfig;
  readonly apiConstructOutputs: ApiConstructOutputs;
  readonly sharedConstructOutputs: SharedConstructOutputs;
}

export interface WorkspaceOutputs {
  byUserIdIndex: string;
}

export class WorkspaceStack extends Stack implements WorkspaceOutputs {

  public readonly byUserIdIndex: string = "byUserId";
  public readonly bySessionIdIndex: string = "bySessionId";
  public readonly byTimestampIndex: string = "byTimestamp";
  private iamHelper: IAMHelper;
  public wsEndpoint: string = "";

  constructor(scope: Construct, id: string, props: WorkspaceProps) {
    super(scope, id);

    const randomUuid = uuidv4();

    this.iamHelper = props.sharedConstructOutputs.iamHelper;
    const genMethodOption = props.apiConstructOutputs.genMethodOption;

    const chatQueueConstruct = new QueueConstruct(this, "LLMQueueStack", {
      namePrefix: Constants.WORKSPACE_API_QUEUE_NAME,
    });

    const portalConstruct = new PortalConstruct(this, "WorkspaceUI");
    const userConstruct = new UserConstruct(this, "WorkspaceUser", {
      adminEmail: props.config.email,
      callbackUrl: portalConstruct.portalUrl,
      userPoolName: `${Constants.SOLUTION_NAME}-workspace_UserPool`,
      domainPrefix: `${Constants.SOLUTION_NAME.toLowerCase()}-workspace-${Aws.ACCOUNT_ID}`,
    });

    const sessionIdAttr = {
      name: "sessionId",
      type: dynamodb.AttributeType.STRING,
    }
    const userIdAttr = {
      name: "userId",
      type: dynamodb.AttributeType.STRING,
    }
    const messageIdAttr = {
      name: "messageId",
      type: dynamodb.AttributeType.STRING,
    }
    const timestampAttr = {
      name: "createTimestamp",
      type: dynamodb.AttributeType.STRING,
    }

    const customerSessionsTable = new DynamoDBTable(this, "CustomerSession", sessionIdAttr, userIdAttr).table;
    customerSessionsTable.addGlobalSecondaryIndex({
      indexName: this.byTimestampIndex,
      partitionKey: userIdAttr,
      sortKey: timestampAttr,
      projectionType: dynamodb.ProjectionType.ALL,
    });

    const customerMessagesTable = new DynamoDBTable(this, "CustomerMessage", messageIdAttr, sessionIdAttr).table;
    customerMessagesTable.addGlobalSecondaryIndex({
      indexName: this.bySessionIdIndex,
      partitionKey: { name: "sessionId", type: dynamodb.AttributeType.STRING },
    });

    const queryHandler = new PythonFunction(this, "QueryHandler", {
      // functionName: `query-handler-${randomUuid}`,
      runtime: Runtime.PYTHON_3_12,
      entry: join(__dirname, "../../../lambda/query_handler"),
      index: "main.py",
      handler: "main.lambda_handler",
      timeout: Duration.minutes(15),
      environment: {
        SESSIONS_TABLE_NAME: customerSessionsTable.tableName,
        MESSAGES_TABLE_NAME: customerMessagesTable.tableName,
        SESSIONS_BY_TIMESTAMP_INDEX_NAME: "byTimestamp",
        MESSAGES_BY_SESSION_ID_INDEX_NAME: "bySessionId",
      },
    });
    queryHandler.addToRolePolicy(this.iamHelper.dynamodbStatement);

    queryHandler.addToRolePolicy(chatQueueConstruct.sqsStatement);
    queryHandler.addEventSource(
      new lambdaEventSources.SqsEventSource(chatQueueConstruct.messageQueue, { batchSize: 1 }),
    );
   
    // Define the API Gateway
    const workspaceApi = new apigw.RestApi(this, `${Constants.SOLUTION_SHORT_NAME.toLowerCase()}-workspace-api`, {
      description: `${Constants.SOLUTION_NAME} - Agent Workspace API`,
      endpointConfiguration: {
        types: [apigw.EndpointType.REGIONAL],
      },
      defaultCorsPreflightOptions: {
        allowHeaders: [
          "Content-Type",
          "X-Amz-Date",
          "Authorization",
          "X-Api-Key",
          "Author",
          "X-Amz-Security-Token",
        ],
        allowMethods: apigw.Cors.ALL_METHODS,
        allowCredentials: true,
        allowOrigins: apigw.Cors.ALL_ORIGINS,
      },
      deployOptions: {
        stageName: "prod",
        metricsEnabled: true,
        loggingLevel: apigw.MethodLoggingLevel.INFO,
        dataTraceEnabled: true,
        tracingEnabled: true,
      },
    });

    const lambdaLayers = new LambdaLayers(this);
    // const sharedLayer = lambdaLayers.createSharedLayer();
    const apiLambdaAuthorizerLayer = lambdaLayers.createAuthorizerLayer();

    const customAuthorizerLambda = new LambdaFunction(this, "CustomAuthorizerLambda", {
      code: Code.fromAsset(join(__dirname, "../../../lambda/authorizer")),
      handler: "custom_authorizer.lambda_handler",
      environment: {
        USER_POOL_ID: userConstruct.userPool.userPoolId,
        REGION: Aws.REGION,
        APP_CLIENT_ID: userConstruct.oidcClientId,
      },
      layers: [apiLambdaAuthorizerLayer],
      statements: [props.sharedConstructOutputs.iamHelper.logStatement],
    });


    const auth = new apigw.RequestAuthorizer(this, 'ApiAuthorizer', {
      handler: customAuthorizerLambda.function,
      identitySources: [apigw.IdentitySource.header('Authorization')],
    });

    const apiResourceSessions = workspaceApi.root.addResource("customer-sessions");
    apiResourceSessions.addMethod("GET", new apigw.LambdaIntegration(queryHandler), genMethodOption(workspaceApi, auth, null),);
    apiResourceSessions.addMethod("POST", new apigw.LambdaIntegration(queryHandler), genMethodOption(workspaceApi, auth, null),);
    const apiResourceMessages = apiResourceSessions.addResource('{sessionId}').addResource("messages");
    apiResourceMessages.addMethod("GET", new apigw.LambdaIntegration(queryHandler), genMethodOption(workspaceApi, auth, null),);
    
    const wsDispatcher = new LambdaFunction(this, "workspaceDispatcher", {
      code: Code.fromAsset(join(__dirname, "../../../lambda/workspace")),
      environment: {
        SQS_QUEUE_URL: chatQueueConstruct.messageQueue.queueUrl,
      },
      statements: [chatQueueConstruct.sqsStatement],
    });

    const webSocketApi = new WSWebSocketConstruct(this, "WSWebSocketApi", {
      dispatcherLambda: wsDispatcher.function,
      sendMessageLambda: queryHandler,
      customAuthorizerLambda: customAuthorizerLambda.function,
      sessionTableName: customerSessionsTable.tableName,
      messageTableName: customerMessagesTable.tableName,
      sessionIndex: "byTimestamp",
      messageIndex: "bySessionId",
    });
    let wsStage = webSocketApi.websocketApiStage
    this.wsEndpoint = `${wsStage.api.apiEndpoint}/${wsStage.stageName}/`;
  }
}