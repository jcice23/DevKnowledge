export type Mode = 'rag' | 'chat';
export type Citation = { number: number; chunk_id: string; filename: string; text: string; score: number; metadata: Record<string, unknown> };
export type Message = { id: string; role: 'user' | 'assistant'; text: string; mode: Mode; citations?: Citation[] };
export type Conversation = { id: string; title: string; messages: Message[]; updated: number };
export type Upload = { id: string; name: string; status: 'pending' | 'success' | 'error'; error?: string };
export class ApiError extends Error {
  constructor(message:string, public status:number) { super(message); }
}
export async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180000);
  try { response = await fetch(`/api${path}`, {...init, signal:controller.signal}); }
  catch { throw new Error(controller.signal.aborted
    ? '等待服务响应超时，请稍后重试。' : '无法连接服务，请确认后端已启动，然后重试。'); }
  finally { clearTimeout(timer); }
  if(response.status===204)return undefined as T;
  let body: any;
  try { body = await response.json(); } catch { throw new Error('服务暂时不可用，请检查后端连接。'); }
  if (!response.ok || body.sucess === false) {
    const labels: Record<number,string> = { 422: '请求参数有误，请检查输入。', 503: '知识库服务尚未就绪，请检查配置或入库报告。', 502: '模型或检索服务暂时不可用，请稍后重试。' };
    const detail = typeof body.detail === 'string' ? body.detail : undefined;
    throw new ApiError(labels[response.status] || detail || body.message || '请求失败，请稍后重试。',response.status);
  }
  return body as T;
}
export const chat = (question: string, mode: Mode) => request<{data:string; citations:Citation[]}>('/chat', {
  method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_input:question, mode}),
});
export type ChatPayload = {user_input:string;mode:Mode;top_k?:number;min_score?:number;document_ids?:string[]|null;user_location?:Record<string,unknown>|null};
export type ServerConversation = {id:string;title:string;updated_at:number;summary?:string};
export type ServerTurn = {request_id:string;seq:number;status:'processing'|'completed'|'failed'|'imported';error:string|null;messages:Message[];request:ChatPayload;response:unknown};
export type HistoryPage = {conversation:ServerConversation;data:ServerTurn[];next_before:number|null;processing_request_id:string|null};
export const conversationsApi = {
  list:(offset=0)=>request<{data:ServerConversation[];next_offset:number|null}>(`/conversations?offset=${offset}`,{method:'GET'}),
  create:()=>request<{data:ServerConversation}>('/conversations',{method:'POST'}),
  history:(id:string,before?:number)=>request<HistoryPage>(`/conversations/${encodeURIComponent(id)}${before?`?before=${before}`:''}`,{method:'GET'}),
  status:(id:string,rid:string)=>request<{data:ServerTurn}>(`/conversations/${encodeURIComponent(id)}/requests/${encodeURIComponent(rid)}`,{method:'GET'}),
  remove:(id:string)=>request<void>(`/conversations/${encodeURIComponent(id)}`,{method:'DELETE'}),
  send:(id:string,rid:string,payload:ChatPayload)=>request('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,conversation_id:id,request_id:rid})}),
  import:(conversation:Conversation)=>request<{data:ServerConversation}>('/conversations/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
    source_id:conversation.id,title:conversation.title,messages:conversation.messages.map(m=>({
      role:m.role,text:m.text,mode:m.mode==='chat'?'chat':'rag',
      citations:(m.citations||[]).filter(c=>Number.isInteger(c.number)&&c.number>0&&typeof c.text==='string'&&typeof c.filename==='string'&&Number.isFinite(c.score)&&c.metadata&&['chunk_id','document_id','ingestion_id'].every(k=>typeof (c as any)[k]==='string')&&Number.isInteger((c as any).chunk_index)),
    })),
  })}),
};
export type DocumentRecord = { document_id:string; original_filename:string; status:'queued'|'processing'|'ready'|'failed'; chunk_count:number|null; error:string|null };
export const upload = (file: File) => { const body = new FormData(); body.append('file', file); return request<{data:DocumentRecord}>('/upload',{method:'POST',body}); };
// 局域网 HTTP 不是安全上下文，不能依赖 randomUUID()。
export const uid = () => crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), b=>b.toString(16).padStart(2,'0')).join('');
export function loadHistory(): { conversations: Conversation[]; uploads: Upload[]; warning: boolean } {
  try {
    const data = JSON.parse(localStorage.getItem('jc.history.v1') || '{"conversations":[],"uploads":[]}');
    if (!Array.isArray(data.conversations) || !Array.isArray(data.uploads)) throw Error();
    for (const c of data.conversations) {
      if (typeof c.id !== 'string' || typeof c.title !== 'string' || !Array.isArray(c.messages)) throw Error();
      for (const m of c.messages) if (typeof m.text !== 'string' || !['user','assistant'].includes(m.role)) throw Error();
    }
    return {conversations:data.conversations, uploads:data.uploads.filter((u:Upload)=>u.status !== 'pending'), warning:false};
  } catch { return {conversations:[], uploads:[], warning:true}; }
}
