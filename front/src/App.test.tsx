import { beforeEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { ApiError, conversationsApi as api, type HistoryPage, type ServerTurn } from './api';
const citation={number:2,chunk_id:'abc',document_id:'doc',ingestion_id:'v',chunk_index:0,filename:'手册.md',text:'引用原文内容',score:.85,metadata:{page_number:7}};
const response=(data:unknown,status=200)=>({ok:status<400,status,json:async()=>data}) as Response;
let history:HistoryPage;
const turn=(rid:string,text='测试问题',reply='回答'):ServerTurn=>({request_id:rid,seq:1,status:'completed',error:null,response:null,request:{user_input:text,mode:'chat'},messages:[{id:rid+'u',role:'user',text,mode:'chat'},{id:rid+'a',role:'assistant',text:reply,mode:'chat',citations:[citation]}]});
beforeEach(()=>{
  history={conversation:{id:'c',title:'服务器会话',updated_at:1},data:[],next_before:null,processing_request_id:null};
  vi.spyOn(api,'list').mockImplementation(async()=>({data:history.data.length?[history.conversation]:[],next_offset:null}));
  vi.spyOn(api,'create').mockResolvedValue({data:history.conversation});
  vi.spyOn(api,'history').mockImplementation(async()=>structuredClone(history));
  vi.spyOn(api,'status').mockImplementation(async(_cid,rid)=>{const data=history.data.find(t=>t.request_id===rid);if(!data)throw new ApiError('请求尚未创建',404);return {data:structuredClone(data)};});
  vi.spyOn(api,'send').mockImplementation(async(_cid,rid,payload)=>{const record=turn(rid,payload.user_input);record.request=payload;history.data=[...history.data.filter(t=>t.request_id!==rid),record];return {};});
  vi.spyOn(api,'remove').mockImplementation(async()=>{history.data=[];});
  vi.spyOn(api,'import').mockResolvedValue({data:history.conversation});
});
function send(text='测试问题'){fireEvent.change(screen.getByLabelText('输入问题'),{target:{value:text}});fireEvent.click(screen.getByLabelText('发送问题'));}
describe('服务器多轮会话',()=>{
  it('首次发送才创建会话，模式切换沿用会话 ID',async()=>{
    render(<App/>);expect(api.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('把想法理清楚'));fireEvent.click(screen.getByLabelText('发送问题'));
    expect(await screen.findByText('回答')).toBeInTheDocument();
    await waitFor(()=>expect(screen.getByLabelText('输入问题')).toBeEnabled());
    expect(api.send).toHaveBeenCalledWith('c',expect.any(String),{user_input:'帮我梳理一下这个想法：',mode:'chat'});
    fireEvent.click(screen.getByRole('button',{name:/^知识库$/}));send('继续解释');
    await waitFor(()=>expect(api.send).toHaveBeenCalledTimes(2));expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.send).toHaveBeenLastCalledWith('c',expect.any(String),{user_input:'继续解释',mode:'rag'});
  });
  it('失败重试先核对状态，复用请求 ID，不重复插入问题',async()=>{
    vi.mocked(api.send).mockRejectedValueOnce(new ApiError('模型失败',502));
    render(<App/>);send();expect(await screen.findByRole('alert')).toHaveTextContent('模型失败');
    fireEvent.click(screen.getByText('重新尝试'));expect(await screen.findByText('回答')).toBeInTheDocument();
    expect(vi.mocked(api.send).mock.calls[0][1]).toBe(vi.mocked(api.send).mock.calls[1][1]);
    expect(screen.getAllByText('测试问题')).toHaveLength(1);expect(api.status).toHaveBeenCalled();
  });
  it('响应丢失但服务器完成时恢复答案，不重新生成',async()=>{
    vi.mocked(api.send).mockImplementationOnce(async(_cid,rid,payload)=>{history.data=[turn(rid,payload.user_input,'服务器已完成')];throw Error('网络断开');});
    render(<App/>);send();expect(await screen.findByText('服务器已完成')).toBeInTheDocument();
    expect(api.send).toHaveBeenCalledTimes(1);expect(screen.queryByText('重新尝试')).not.toBeInTheDocument();
  });
  it('刷新后恢复未提交请求，允许用原 ID 重试',async()=>{
    localStorage.setItem('jc.ui.v2',JSON.stringify({active:'c',pending:{cid:'c',rid:'unsubmitted',payload:{user_input:'未提交的问题',mode:'chat'}}}));
    render(<App/>);expect(await screen.findByRole('alert')).toHaveTextContent('尚未提交');
    fireEvent.click(screen.getByText('重新尝试'));expect(await screen.findByText('回答')).toBeInTheDocument();
    expect(api.send).toHaveBeenCalledWith('c','unsubmitted',{user_input:'未提交的问题',mode:'chat'});
  });
  it('刷新恢复历史，窗口聚焦更新另一设备回答',async()=>{
    localStorage.setItem('jc.ui.v2',JSON.stringify({active:'c'}));history.data=[turn('old','旧问题','旧回答')];
    render(<App/>);expect(await screen.findByText('旧回答')).toBeInTheDocument();
    history.data.push({...turn('other','新问题','另一设备的回答'),seq:2});fireEvent(window,new Event('focus'));
    expect(await screen.findByText('另一设备的回答')).toBeInTheDocument();expect(api.send).not.toHaveBeenCalled();
  });
  it('处理中恢复后禁用发送，轮询到完成状态',async()=>{
    localStorage.setItem('jc.ui.v2',JSON.stringify({active:'c'}));history.data=[{...turn('run'),status:'processing',messages:turn('run').messages.slice(0,1)}];history.processing_request_id='run';
    render(<App/>);await screen.findByText('测试问题');expect(screen.getByLabelText('输入问题')).toBeDisabled();
    history.data=[turn('run','测试问题','后台完成')];history.processing_request_id=null;
    expect(await screen.findByText('后台完成',{}, {timeout:3500})).toBeInTheDocument();expect(screen.getByLabelText('输入问题')).toBeEnabled();
  });
  it('删除共享会话需确认，新建会话不带旧消息',async()=>{
    localStorage.setItem('jc.ui.v2',JSON.stringify({active:'c'}));history.data=[turn('old','旧问题','旧回答')];vi.spyOn(window,'confirm').mockReturnValue(true);
    render(<App/>);await screen.findByText('旧回答');fireEvent.click(screen.getByText('开启新对话'));expect(screen.queryByText('旧回答')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('删除对话 服务器会话'));await waitFor(()=>expect(api.remove).toHaveBeenCalledWith('c'));expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('服务器'));
  });
  it('摘要可查看，引用正确映射且 HTML 不执行',async()=>{
    localStorage.setItem('jc.ui.v2',JSON.stringify({active:'c'}));history.data=[turn('old','问题','答案[2]\n\n<script>alert(1)</script>')];history.conversation.summary='用户希望用中文解释';
    render(<App/>);fireEvent.click(await screen.findByText('较早内容已整理为摘要 · 查看摘要'));expect(screen.getByText('用户希望用中文解释')).toBeInTheDocument();fireEvent.click(screen.getByLabelText('关闭面板'));
    fireEvent.click(screen.getByLabelText('查看引用 2'));expect(screen.getByText('引用原文内容')).toBeInTheDocument();expect(document.querySelector('script')).toBeNull();
  });
  it('旧记录仅手动导入且重复提交同一来源，不清除本机记录',async()=>{
    const old={id:'legacy',title:'旧会话',updated:1,messages:turn('old').messages};const saved=JSON.stringify({conversations:[old],uploads:[]});localStorage.setItem('jc.history.v1',saved);vi.spyOn(window,'confirm').mockReturnValue(true);
    render(<App/>);expect(api.import).not.toHaveBeenCalled();fireEvent.click(screen.getByText('导入本机旧对话'));await screen.findByText(/旧对话导入完成/);
    fireEvent.click(screen.getByText('导入本机旧对话'));await waitFor(()=>expect(api.import).toHaveBeenCalledTimes(2));expect(api.import).toHaveBeenNthCalledWith(1,old);expect(api.import).toHaveBeenNthCalledWith(2,old);expect(localStorage.getItem('jc.history.v1')).toBe(saved);
  });
  it('偏好存储失败不影响服务器会话',async()=>{
    vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota');});render(<App/>);expect(screen.getByRole('status')).toHaveTextContent('服务器会话仍可正常使用');send();expect(await screen.findByText('回答')).toBeInTheDocument();
  });
  it('中文输入法、Shift Enter 和重复点击不误发',async()=>{
    let resolve!:(value:unknown)=>void;vi.mocked(api.send).mockReturnValue(new Promise(r=>resolve=r));render(<App/>);const input=screen.getByLabelText('输入问题');fireEvent.change(input,{target:{value:'问题'}});
    fireEvent.keyDown(input,{key:'Enter',isComposing:true});fireEvent.keyDown(input,{key:'Enter',shiftKey:true});expect(api.send).not.toHaveBeenCalled();fireEvent.keyDown(input,{key:'Enter'});fireEvent.click(screen.getByLabelText('发送问题'));
    await waitFor(()=>expect(api.send).toHaveBeenCalledTimes(1));expect(input).toBeDisabled();resolve({});await waitFor(()=>expect(input).toBeEnabled());
  });
  it('文档上传继续显示队列与失败状态',async()=>{
    const doc={document_id:'d',original_filename:'a.txt',status:'queued',chunk_count:null,error:null};vi.spyOn(globalThis,'fetch').mockImplementation(async(url,init)=>{if(url==='/api/documents')return response({data:[doc],worker_available:true});const file=(init?.body as FormData).get('file') as File;return file.name==='a.txt'?response({data:doc}):response({detail:'文件过大'},413);});
    render(<App/>);fireEvent.click(screen.getByText('文档上传'));await userEvent.setup().upload(screen.getByLabelText('选择文档'),[new File(['hello'],'a.txt',{type:'text/plain'}),new File(['world'],'b.txt',{type:'text/plain'})]);expect(await screen.findByText('b.txt：文件过大')).toBeInTheDocument();expect(screen.getByText('排队等待入库')).toBeInTheDocument();
  });
});
