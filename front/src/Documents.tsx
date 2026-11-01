import { useEffect, useRef, useState } from 'react';
import { FileText, UploadCloud } from 'lucide-react';
import { request, upload, type DocumentRecord } from './api';

const labels = { queued: '排队等待入库', processing: '正在解析并入库…', ready: '已入库，可检索', failed: '入库失败' };

export default function Documents() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [failures, setFailures] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [retrying, setRetrying] = useState<string|null>(null);
  const [workerAvailable, setWorkerAvailable] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const busy = useRef(false);
  const retryBusy = useRef(false);
  const refresh = useRef<()=>void>(()=>{});

  useEffect(()=>{
    let disposed=false;
    let running=false;
    async function load() {
      if(running)return;
      running=true;
      try {
        const result=await request<{data:DocumentRecord[];worker_available:boolean}>('/documents', {method:'GET'});
        if(!disposed){setDocuments(result.data);setWorkerAvailable(result.worker_available);setError('');setLoaded(true);}
      } catch(exc) {if(!disposed)setError(exc instanceof Error?exc.message:'读取文档状态失败');}
      finally {running=false;}
    }
    refresh.current=()=>{void load();};
    void load();
    const timer=setInterval(()=>void load(),2000);
    return ()=>{disposed=true;clearInterval(timer);refresh.current=()=>{};};
  },[]);

  async function selectFiles(files:FileList|null) {
    if(!files || busy.current)return;
    busy.current=true;setUploading(true);setFailures([]);
    try {
      for(const file of Array.from(files)) {
        try {
          if(!/\.(pdf|docx|md|txt)$/i.test(file.name))throw Error('仅支持 PDF、DOCX、MD、TXT 文件');
          const result=await upload(file);
          setDocuments(prev=>[result.data,...prev.filter(d=>d.document_id!==result.data.document_id)]);
        } catch(exc) {setFailures(prev=>[...prev,`${file.name}：${exc instanceof Error?exc.message:'上传失败'}`]);}
      }
    } finally {busy.current=false;setUploading(false);refresh.current();}
  }

  async function retry(id:string) {
    if(retryBusy.current)return;
    retryBusy.current=true;setRetrying(id);
    try {
      const result=await request<{data:DocumentRecord}>(`/documents/${encodeURIComponent(id)}/retry`,{method:'POST'});
      setDocuments(prev=>prev.map(d=>d.document_id===id?result.data:d));
    } catch(exc) {setError(exc instanceof Error?exc.message:'重试失败');}
    finally {retryBusy.current=false;setRetrying(null);}
  }

  return <>
    <p className="drawer-intro">文件保存在项目目录，上传后自动解析、分块并入库。</p>
    <label className={`upload-zone ${uploading?'disabled':''}`}><UploadCloud size={32}/><strong>{uploading?'正在上传文档…':'选择要上传的文档'}</strong><span>PDF、DOCX、Markdown、TXT · 支持多选</span><input type="file" multiple accept=".pdf,.docx,.md,.txt" aria-label="选择文档" disabled={uploading} onChange={e=>{void selectFiles(e.target.files);e.target.value='';}}/></label>
    <p className="upload-explainer">状态变为“已入库，可检索”后，即可在知识库模式提问。关闭面板不会中断后台入库。</p>
    {error&&<p role="alert" className="error-text">{error}</p>}
    {!workerAvailable&&<p role="status">入库工作进程尚未就绪，文档将保留在队列中。请检查后端配置并重启服务。</p>}
    {failures.map((text,index)=><p role="alert" className="error-text" key={index}>{text}</p>)}
    <h3 className="upload-list-title">服务器上传文档 <span>{documents.length}</span></h3>
    <p className="drawer-intro">展示当前集合通过网页上传的文档；既有离线导入资料仍可检索。</p>
    {!loaded&&!error&&<p role="status">正在读取文档状态…</p>}
    {loaded&&!documents.length&&<p className="empty-history">还没有上传文档，添加你的第一份资料吧。</p>}
    <div className="upload-list">{documents.map(d=><div className="upload-row" key={d.document_id}>
      <FileText size={20}/><div><strong>{d.original_filename}</strong><p className={d.status==='failed'?'error-text':''}>{labels[d.status]}{d.status==='ready'?` · ${d.chunk_count} 个分块`:''}</p>{d.error&&<p className="error-text">{d.error}</p>}</div>
      {d.status==='failed'&&<button className="copy-btn" disabled={retrying!==null} onClick={()=>void retry(d.document_id)}>{retrying===d.document_id?'提交中…':'重试入库'}</button>}
    </div>)}</div>
  </>;
}
