import { useEffect, useState } from 'react';
import { axios } from 'src/utils/request';
import {
  Box,
  Button,
  ExpandableSection,
  FileUpload,
  Form,
  FormField,
  Header,
  Input,
  Modal,
  ProgressBar,
  Select,
  SelectProps,
  SpaceBetween,
} from '@cloudscape-design/components';
import { alertMsg, validateNameTagString } from 'src/utils/utils';
import { AxiosProgressEvent } from 'axios';
import { useTranslation } from 'react-i18next';
import useAxiosRequest from 'src/hooks/useAxiosRequest';
import { ExecutionResponse, PresignedUrlResponse } from 'src/types';
import { DOC_INDEX_TYPE_LIST } from 'src/utils/const';
import { useAuth } from 'react-oidc-context';

interface AddIntentionProps {
  showAddModal: boolean;
  setShowAddModal: (show: boolean) => void;
  reloadLibrary: () => void;
}

interface SelectedOption {
  value: string;
  label: string;
}

const AddIntention: React.FC<AddIntentionProps> = (props: AddIntentionProps) => {
  const { t } = useTranslation();
  const auth = useAuth();
  const { showAddModal, setShowAddModal, reloadLibrary } = props;
  const fetchData = useAxiosRequest();
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [showProgress, setShowProgress] = useState(false);
  const [fileEmptyError, setFileEmptyError] = useState(false);

  const [indexName, setIndexName] = useState('');
  const [indexNameError, setIndexNameError] = useState('');
  const [indexType, setIndexType] = useState<SelectProps.Option>(
    DOC_INDEX_TYPE_LIST[0],
  );
  const [tagName, setTagName] = useState('');
  const [tagNameError, setTagNameError] = useState('');
  const [advanceExpand, setAdvanceExpand] = useState(false);
  const [selectedBot, setSelectedBot]  = useState<SelectedOption>(null as any);
  const [selectedModel, setSelectedModel]  = useState<SelectedOption>(null as any);
  const [bots, setBots] = useState<SelectedOption[]>([])
  const [models, setModels] = useState<SelectedOption[]>([])


  useEffect(()=>{
    const bots =[{
      value: "default",
      label: "default"
    }]
    const models=[{
      value: "cohere.embed-english-v3",
      label: "cohere.embed-english-v3"
    },{
      value: "cohere.embed-multilingual-v3",
      label: "cohere.embed-multilingual-v3"
    },{
      value: "amazon.titan-embed-text-v1",
      label: "amazon.titan-embed-text-v1"
    },{
      value: "amazon.titan-embed-image-v1",
      label: "amazon.titan-embed-image-v1"
    },{
      value: "amazon.titan-embed-text-v2:0",
      label: "amazon.titan-embed-text-v2:0"
    }]
    setBots(bots)
    setModels(models)
    setSelectedBot(bots[0])
    setSelectedModel(models[0])
  },[])

  const executionKnowledgeBase = async (bucket: string, prefix: string) => {
    const groupName: string[] = auth?.user?.profile?.['cognito:groups'] as any;
    const resExecution: ExecutionResponse = await fetchData({
      url: `/knowledge-base/executions`,
      method: 'post',
      data: {
        s3Bucket: bucket,
        s3Prefix: prefix,
        offline: 'true',
        qaEnhance: 'false',
        chatbotId: groupName?.[0]?.toLocaleLowerCase() ?? 'admin',
        indexId: indexName ? indexName.trim() : undefined,
        indexType: indexType.value,
        operationType: 'create',
        tag: tagName ? tagName.trim() : undefined,
      },
    });
    if (resExecution.execution_id) {
      setIndexName('');
      setTagName('');
    }
  };

  const uploadFilesToS3 = async () => {
    // validate  file
    if (uploadFiles.length <= 0) {
      setFileEmptyError(true);
      return;
    }
    // validate index name
    if (!validateNameTagString(indexName.trim())) {
      setIndexNameError('validation.formatInvalidTagIndex');
      return;
    }
    // validate tag
    if (!validateNameTagString(tagName.trim())) {
      setTagNameError('validation.formatInvalidTagIndex');
      return;
    }
    setShowProgress(true);
    const totalSize = uploadFiles.reduce((acc, file) => acc + file.size, 0);
    let progressMap = new Map();
    let percentage = 0;

    const uploadPromises = uploadFiles.map(async (file) => {
      const resPresignedData: PresignedUrlResponse = await fetchData({
        url: `/knowledge-base/kb-presigned-url`,
        method: 'post',
        data: {
          file_name: file.name,
          content_type: file.type,
        },
      });
      const uploadPreSignUrl = resPresignedData.data;
      return axios.put(uploadPreSignUrl, file, {
        headers: {
          'Content-Type': file.type,
        },
        onUploadProgress: (e: AxiosProgressEvent) => {
          progressMap.set(file.name, {
            loaded: e.loaded,
            total: file.size,
          });
          const totalUploaded = Array.from(progressMap.values()).reduce(
            (acc, curr) => acc + curr.loaded,
            0,
          );
          percentage = Math.floor((totalUploaded / totalSize) * 100);
          setUploadProgress(percentage);
          if (percentage >= 100) {
            executionKnowledgeBase(
              resPresignedData.s3Bucket,
              resPresignedData.s3Prefix,
            );
          }
        },
      });
    });

    try {
      await Promise.all(uploadPromises);
      if (percentage >= 100) {
        setShowProgress(false);
        setUploadFiles([]);
        setUploadProgress(0);
        alertMsg(t('uploadSuccess'), 'success');
        setShowAddModal(false);
        reloadLibrary();
      }
    } catch (error) {
      console.error('error', error);
    }
  };

  return (
    <Modal
      onDismiss={() => setShowAddModal(false)}
      visible={showAddModal}
      footer={
        <Box float="right">
          <SpaceBetween direction="horizontal" size="xs">
            <Button
              disabled={showProgress}
              variant="link"
              onClick={() => {
                setShowAddModal(false);
              }}
            >
              {t('button.cancel')}
            </Button>
            <Button
              loading={showProgress}
              variant="primary"
              onClick={() => {
                uploadFilesToS3();
              }}
            >
              {t('button.upload')}
            </Button>
          </SpaceBetween>
        </Box>
      }
      header={<Header description={t('ingestDesc')}>{t('ingest')}</Header>}
    >
      <SpaceBetween direction="vertical" size="l">
        <Form variant="embedded">
          <SpaceBetween direction="vertical" size="l">
            <FormField
              errorText={fileEmptyError ? t('fileEmptyError') : ''}
              label={t('selectFile')}
              description={t('selectFileDesc')}
            >
              <div className="mt-10">
                <FileUpload
                  onChange={({ detail }) => {
                    setFileEmptyError(false);
                    setUploadFiles(detail.value);
                  }}
                  value={uploadFiles}
                  i18nStrings={{
                    uploadButtonText: (e) =>
                      e ? t('chooseFiles') : t('chooseFile'),
                    dropzoneText: (e) =>
                      e ? t('dropFilesToUpload') : t('dropFileToUpload'),
                    removeFileAriaLabel: (e) => `${t('removeFIle')} ${e + 1}`,
                    limitShowFewer: t('showFewer'),
                    limitShowMore: t('showMore'),
                    errorIconAriaLabel: t('error'),
                  }}
                  multiple={false}
                  showFileLastModified
                  showFileSize
                  accept=".xlsx,.xls"
                  constraintText={`${t('supportFiles')} xlsx, xls.`}
                />
              </div>
            </FormField>
            <div>
              <ExpandableSection
                onChange={({ detail }) => {
                  setAdvanceExpand(detail.expanded);
                }}
                expanded={advanceExpand}
                headingTagOverride="h4"
                headerText={t('additionalSettings')}
              >
                <SpaceBetween direction="vertical" size="l">
                  <FormField label={t('bot')} stretch={true}>
                    <Select
                      options={bots}
                      selectedOption={selectedBot}
                      onChange={({ detail }:{detail: any}) => {
                        setSelectedBot(detail.selectedOption);
                      }}
                    />
                  </FormField>
                  <FormField
                    label={
                      <>
                        {t('indexName')} -{' '}
                        <Box variant="span" fontWeight="normal">
                          <i>{t('optional')}</i>
                        </Box>
                      </>
                    }
                    stretch={true}
                    errorText={t(indexNameError)}
                  >
                    <Input
                      placeholder="example-index-name"
                      value={indexName}
                      onChange={({ detail }) => {
                        setIndexNameError('');
                        setIndexName(detail.value);
                      }}
                    />
                  </FormField>
                  <FormField label={t('model')} stretch={true}>
                    <Select
                      options={models}
                      selectedOption={selectedModel}
                      onChange={({ detail }:{detail: any}) => {
                        setSelectedModel(detail.selectedOption);
                      }}
                    />
                  </FormField>
                  <FormField
                    label={
                      <>
                        {t('tag')} -{' '}
                        <Box variant="span" fontWeight="normal">
                          <i>{t('optional')}</i>
                        </Box>
                      </>
                    }
                    stretch={true}
                    errorText={t(tagNameError)}
                  >
                    <Input
                      placeholder="example-tag"
                      value={tagName}
                      onChange={({ detail }) => {
                        setTagNameError('');
                        setTagName(detail.value);
                      }}
                    />
                  </FormField>
                </SpaceBetween>
              </ExpandableSection>
            </div>
            {showProgress && (
              <FormField>
                <ProgressBar
                  value={uploadProgress}
                  label={t('uploadProgress')}
                />
              </FormField>
            )}
          </SpaceBetween>
        </Form>
      </SpaceBetween>
    </Modal>
  );
};

export default AddIntention;
