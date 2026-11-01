import { useEffect, useRef, useState } from 'react';
import { ApiError, conversationsApi as api, loadHistory, uid, type ChatPayload, type HistoryPage, type Mode, type ServerConversation } from './api';

type Pending = {cid:string;rid:string;payload:ChatPayload};
const reason=(exc:unknown)=>exc instanceof Error?exc.message:'服务暂不可用，请重试';
function loadUi() {
  try{return JSON.parse(localStorage.getItem('jc.ui.v2')||'{}');}catch{return {};}
}

export function useConversations() {
  const [initial]=useState(loadUi);
  const [legacy]=useState(loadHistory);
  const [conversations,setConversations]=useState<ServerConversation[]>([]);
  const [nextOffset,setNextOffset]=useState<number|null>(null);
  const [active,setActive]=useState<string|null>(typeof initial.active==='string'?initial.active:null);
  const activeRef=useRef(active);activeRef.current=active;
  const [draft,setDraft]=useState(typeof initial.draft==='string'?initial.draft:'');
  const [mode,setMode]=useState<Mode>(initial.mode==='chat'?'chat':'rag');
  const [page,setPage]=useState<HistoryPage|null>(null);
  const [pending,setPending]=useState<Pending|null>(initial.pending?.cid&&initial.pending?.rid&&initial.pending?.payload?.user_input?initial.pending:null);
  const [sending,setSending]=useState(false);
  const sendingRef=useRef(false);
  const [loading,setLoading]=useState(false);
  const [notice,setNotice]=useState('');
  const [failure,setFailure]=useState('');
  const [warning,setWarning]=useState(legacy.warning);
  const [importing,setImporting]=useState(false);
  const importBusy=useRef(false);
  const refreshGeneration=useRef(0);
  const mounted=useRef(true);

  useEffect(()=>{try{localStorage.setItem('jc.ui.v2',JSON.stringify({active,draft,mode,pending}));}catch{setWarning(true);}},[active,draft,mode,pending]);

  async function refreshList(append=false) {
    const result=await api.list(append?(nextOffset??0):0);
    if(!mounted.current)return;
    setConversations(prev=>append?[...prev,...result.data.filter(c=>!prev.some(p=>p.id===c.id))]:result.data);
    setNextOffset(result.next_offset);
  }
  async function refresh(id:string) {
    const generation=++refreshGeneration.current;
    const result=await api.history(id);
    if(!mounted.current||activeRef.current!==id||generation!==refreshGeneration.current)return;
    // 保留已加载的较早记录，同时用最新状态替换已存在轮次。
    setPage(prev=>{
      if(prev?.conversation.id!==id)return result;
      const freshIds=new Set(result.data.map(t=>t.request_id));
      const first=result.data[0]?.seq??Infinity;
      const older=prev.data.filter(t=>t.seq<first&&!freshIds.has(t.request_id));
      return {...result,data:[...older,...result.data],next_before:older.length?prev.next_before:result.next_before};
    });
    setPending(current=>{
      if(current?.cid!==id)return current;
      return result.data.some(t=>t.request_id===current.rid&&t.status==='completed')?null:current;
    });
  }
  useEffect(()=>{
    mounted.current=true;
    void refreshList().catch(exc=>setNotice(reason(exc)));
    const focus=()=>{
      void refreshList().catch(exc=>setNotice(reason(exc)));
      if(activeRef.current)void refresh(activeRef.current).catch(exc=>setNotice(reason(exc)));
    };
    window.addEventListener('focus',focus);
    return ()=>{mounted.current=false;window.removeEventListener('focus',focus);};
  },[]);
  useEffect(()=>{
    setPage(null);setFailure('');
    if(!active)return;
    setLoading(true);
    void refresh(active).catch(exc=>{
      if(activeRef.current===active){setNotice(reason(exc));if(exc instanceof ApiError&&exc.status===404){setActive(null);setPending(null);}}
    }).finally(()=>{if(activeRef.current===active)setLoading(false);});
  },[active]);

  const last=page?.data.at(-1);
  const serverBusy=Boolean(page?.processing_request_id);
  const busy=sending||serverBusy;
  const failed=last?.status==='failed'?{cid:active!,rid:last.request_id,payload:last.request}:null;
  const retryTarget=pending?.cid===active?pending:failed;
  const error=failed?last?.error||'请求失败，请重试':failure;
  useEffect(()=>{if(last?.status==='completed')setFailure('');},[last?.status,last?.request_id]);
  useEffect(()=>{
    if(!pending||pending.cid!==active||sending)return;
    let disposed=false;
    void api.status(pending.cid,pending.rid).then(result=>{
      if(disposed)return;
      if(result.data.status==='completed'){setPending(null);setFailure('');}
      else if(result.data.status==='failed')setFailure(result.data.error||'请求失败，请重试');
      return refresh(pending.cid);
    }).catch(exc=>{
      if(!disposed)setFailure(previous=>previous||(exc instanceof ApiError&&exc.status===404?'上次请求尚未提交，可重新尝试。':reason(exc)));
    });
    return ()=>{disposed=true;};
  },[pending,active,sending]);
  useEffect(()=>{
    if(!active||(!serverBusy&&!pending&&!sending))return;
    const timer=setInterval(()=>void refresh(active).catch(exc=>setNotice(reason(exc))),2000);
    return ()=>clearInterval(timer);
  },[active,serverBusy,pending,sending]);

  function choose(id:string|null) {
    if(sendingRef.current)return;
    activeRef.current=id;setActive(id);setDraft('');setFailure('');setPending(null);setNotice('');setLoading(false);
  }
  async function send(retry=false) {
    if(sendingRef.current||serverBusy||loading)return;
    const candidate=retry?retryTarget:null;
    if(retry&&!candidate)return;
    if(!candidate&&!draft.trim())return;
    sendingRef.current=true;setSending(true);setFailure('');setNotice('');
    let target=candidate;
    try{
      if(candidate){
        try{
          const status=await api.status(candidate.cid,candidate.rid);
          if(status.data.status==='completed'){setPending(null);await refresh(candidate.cid);return;}
          if(status.data.status==='processing'){await refresh(candidate.cid);return;}
        }catch(exc){if(!(exc instanceof ApiError&&exc.status===404))throw exc;}
      }
      if(!target){
        let cid=activeRef.current;
        if(!cid){const created=await api.create();cid=created.data.id;activeRef.current=cid;setActive(cid);}
        target={cid,rid:uid(),payload:{user_input:draft.trim(),mode}};
        setPending(target);setDraft('');
      }
      await api.send(target.cid,target.rid,target.payload);
      setPending(null);setFailure('');
      await refresh(target.cid);
      await refreshList();
    }catch(exc){
      setFailure(reason(exc));
      if(target){
        setPending(target);
        // 网络异常可能发生在提交之后，先读状态，不自动重新调用模型。
        try{
          const result=await api.status(target.cid,target.rid);
          if(result.data.status==='completed'){setPending(null);setFailure('');}
          if(result.data.status==='processing')setFailure('请求仍在服务器处理中，正在等待结果。');
          await refresh(target.cid);
        }catch{/* 保留请求标识供手动核对并重试 */}
      }
    }finally{sendingRef.current=false;setSending(false);}
  }
  async function remove(id:string) {
    if(!window.confirm('删除服务器上的这段对话及摘要？其他设备也将无法查看。'))return;
    try{await api.remove(id);if(active===id)choose(null);await refreshList();}catch(exc){setNotice(reason(exc));}
  }
  async function loadOlder() {
    if(!active||!page?.next_before||loading)return;
    setLoading(true);
    try{
      const result=await api.history(active,page.next_before);
      if(activeRef.current===active)setPage(prev=>prev?{...prev,data:[...result.data.filter(t=>!prev.data.some(p=>p.request_id===t.request_id)),...prev.data],next_before:result.next_before}:result);
    }catch(exc){setNotice(reason(exc));}finally{setLoading(false);}
  }
  async function importLegacy() {
    if(importBusy.current||!window.confirm('将本机旧对话导入服务器？局域网访问设备将能查看，原本机记录会保留。'))return;
    importBusy.current=true;setImporting(true);
    try{
      for(const conversation of legacy.conversations)if(conversation.messages.length)await api.import(conversation);
      await refreshList();setNotice('旧对话导入完成；重复导入不会创建副本。');
    }catch(exc){setNotice(`导入未完成，可重试：${reason(exc)}`);}finally{importBusy.current=false;setImporting(false);}
  }
  const messages=page?.conversation.id===active?page.data.flatMap(t=>t.messages):[];
  // 上传请求尚未出现在服务器查询结果中时，仍展示本轮问题。
  if(pending?.cid===active&&!page?.data.some(t=>t.request_id===pending.rid))messages.push({id:pending.rid+'-user',role:'user',text:pending.payload.user_input,mode:pending.payload.mode});
  return {conversations,active,draft,setDraft,mode,setMode,busy,loading,notice,warning,page,messages,
    error,retryTarget,send,choose,remove,loadOlder,importLegacy,importing,legacyCount:legacy.conversations.length,
    nextOffset,loadMore:()=>void refreshList(true).catch(exc=>setNotice(reason(exc))),
    reload:()=>{void refreshList().catch(exc=>setNotice(reason(exc)));if(active)void refresh(active).catch(exc=>setNotice(reason(exc)));}};
}
