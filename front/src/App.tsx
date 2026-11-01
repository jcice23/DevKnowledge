import { useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowUp, Plus, MessageSquare, BookOpen, Sparkles, Feather, ArrowUpRight, PanelLeftClose, Menu, X, FileText, Copy, Trash2, ChevronRight, Leaf, LoaderCircle } from 'lucide-react';
import Documents from './Documents';
import { type Citation, type Message, type Mode } from './api';
import { useConversations } from './useConversations';

function remarkCitations() {
  return (tree: any) => {
    function walk(node:any) {
      if (!node.children || ['link','code','inlineCode'].includes(node.type)) return;
      node.children = node.children.flatMap((child:any) => {
        if (child.type !== 'text') { walk(child); return [child]; }
        const parts = child.value.split(/(\[\d+\])/g);
        return parts.filter(Boolean).map((part:string) => /^\[\d+\]$/.test(part)
          ? {type:'link', url:`#cite-${part.slice(1,-1)}`, children:[{type:'text',value:part}]} : {type:'text',value:part});
      });
    }
    walk(tree);
  };
}
function Modal({ title, children, close }: {title:string; children:ReactNode; close:()=>void}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(()=>{ const d=ref.current!; d.showModal(); return ()=>d.close(); },[]);
  return <dialog ref={ref} className="drawer" aria-label={title} onCancel={e=>{e.preventDefault();close();}} onClick={e=>{if(e.target===e.currentTarget)close();}}>
    <div className="drawer-content"><header><div><span className="eyebrow">YOUR PERSONAL SPACE</span><h2>{title}</h2></div><button className="icon-btn" aria-label="关闭面板" onClick={close}><X size={20}/></button></header>{children}</div>
  </dialog>;
}
function CopyButton({text}:{text:string}) {
  const [label,setLabel]=useState('复制');
  return <button className="copy-btn" onClick={async()=>{try{await navigator.clipboard.writeText(text);setLabel('已复制');}catch{setLabel('复制失败，请手动选择');}}}><Copy size={14}/>{label}</button>;
}
function Answer({message, openCitation}:{message:Message;openCitation:(c:Citation)=>void}) {
  return <><div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm,remarkCitations]} components={{
    a:({href,children})=>{
      const number=Number(href?.match(/^#cite-(\d+)$/)?.[1]);
      const citation=message.citations?.find(c=>c.number===number);
      return citation ? <button className="inline-cite" onClick={()=>openCitation(citation)} aria-label={`查看引用 ${number}`}>{children}</button>
        : href?.startsWith('#cite-') ? <span>{children}</span> : <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
    },
    pre:({children})=><div className="code-block"><pre>{children}</pre></div>,
  }}>{message.text}</ReactMarkdown></div>
  {!!message.citations?.length && <div className="sources"><span>参考来源</span>{message.citations.map(c=><button key={c.number} onClick={()=>openCitation(c)}><FileText size={14}/><b>{c.number}</b>{c.filename}<ChevronRight size={13}/></button>)}</div>}
  <CopyButton text={message.text}/></>;
}

export default function App() {
  const state=useConversations();
  const {conversations,active,draft,setDraft,mode,setMode,busy,messages,send}=state;
  const [sidebar,setSidebar]=useState(false);
  const [panel,setPanel]=useState<'upload'|'summary'|null>(null);
  const [citation,setCitation]=useState<Citation|null>(null);
  const input=useRef<HTMLTextAreaElement>(null);
  const end=useRef<HTMLDivElement>(null);
  const current=state.page?.conversation || conversations.find(c=>c.id===active);
  useEffect(()=>{end.current?.scrollIntoView?.({behavior:'smooth'});},[messages.length,busy]);
  function newConversation(){state.choose(null);setSidebar(false);input.current?.focus();}
  function starter(text:string,next:Mode){setDraft(text);setMode(next);input.current?.focus();}
  return <div className="app-shell">
    {sidebar && <button className="sidebar-backdrop" aria-label="关闭导航" onClick={()=>setSidebar(false)}/>}
    <aside className={`sidebar ${sidebar?'open':''}`}>
      <div className="brand"><div className="brand-mark">jc<span>✳</span></div><div><strong>JC 助手</strong><small>留一点空间，给好想法。</small></div><button className="icon-btn mobile-only" aria-label="关闭导航" onClick={()=>setSidebar(false)}><PanelLeftClose size={18}/></button></div>
      <button className="new-chat" onClick={newConversation} disabled={busy}><Plus size={18}/>开启新对话<span>↗</span></button>
      <div className="nav-label">我的空间</div>
      <button className="nav-item selected" onClick={()=>{setPanel(null);setSidebar(false);}}><MessageSquare size={18}/>与 JC 聊聊<span className="tiny-dot"/></button>
      <button className="nav-item" onClick={()=>{setPanel('upload');setSidebar(false);}}><BookOpen size={18}/>文档上传<ChevronRight size={15}/></button>
      <div className="history-heading"><span>最近对话</span><span>{conversations.length?String(conversations.length).padStart(2,'0'):''}</span></div>
      <div className="history-list">{!conversations.length?<p className="empty-history">每个好想法，都从一句话开始。<br/>你的对话会出现在这里。</p>:conversations.map(c=><div className={`history-item ${active===c.id?'active':''}`} key={c.id}><button disabled={busy} onClick={()=>{state.choose(c.id);setSidebar(false);}}>{c.title}</button><button className="delete-chat" aria-label={`删除对话 ${c.title}`} disabled={busy} onClick={()=>void state.remove(c.id)}><Trash2 size={13}/></button></div>)}</div>
      {state.nextOffset!==null&&<button className="copy-btn" onClick={state.loadMore}>更多会话</button>}
      {state.legacyCount>0&&<button className="copy-btn" onClick={()=>void state.importLegacy()} disabled={state.importing}>{state.importing?'正在导入…':'导入本机旧对话'}</button>}
      <div className="sidebar-note"><Leaf size={18}/><p>不必一次想清楚。<br/><strong>我们可以慢慢来。</strong></p></div>
      <div className="profile"><span className="avatar">我</span><div><strong>我的个人空间</strong><small>只属于你的日常灵感</small></div><span className="profile-dot"/></div>
    </aside>
    <main className="main-panel">
      <header className="topbar"><div className="topbar-title"><button className="icon-btn mobile-only" aria-label="打开导航" onClick={()=>setSidebar(true)}><Menu size={20}/></button><span>个人助手</span><span className="divider">/</span><strong>{current?.title || '新的开始'}</strong></div><span className="topbar-note"><span/>一点灵感，一点进步</span></header>
      {state.warning&&<div className="storage-warning" role="status">本机偏好存储不可用或旧记录损坏；服务器会话仍可正常使用。</div>}
      {state.notice&&<div className="storage-warning" role="status">{state.notice}<button className="copy-btn" onClick={state.reload}>刷新</button></div>}
      {state.loading&&<div className="processing" role="status">正在读取会话…</div>}
      {!messages.length&&state.error&&<div className="request-error" role="alert">{state.error}</div>}
      {state.page?.conversation.summary&&<button className="summary-banner" onClick={()=>setPanel('summary')}>较早内容已整理为摘要 · 查看摘要</button>}
      <section className={`chat-scroll ${!messages.length?'welcome-scroll':''}`} aria-label="对话记录">
        {!messages.length?<div className="welcome"><div className="greeting-badge"><span className="small-sun">✳</span> 你的日常，也值得一个好帮手</div><h1>今天想一起<br className="mobile-only"/>解决什么<span>？</span></h1><p className="welcome-description">一个问题，一点灵感，或是还没成形的想法。<br/>交给 JC，我们一起理清头绪。</p><div className="suggestions">
          <button onClick={()=>starter('帮我梳理一下这个想法：','chat')}><span className="suggestion-icon peach"><Feather size={23}/></span><strong>把想法理清楚</strong><p>从零散的灵感，走向清晰的下一步</p><ArrowUpRight size={17}/></button>
          <button onClick={()=>starter('请用简单易懂的方式解释：','chat')}><span className="suggestion-icon sage"><Sparkles size={23}/></span><strong>一起学点新东西</strong><p>换个角度，让复杂的问题变简单</p><ArrowUpRight size={17}/></button>
          <button onClick={()=>starter('正则表达式中的 \\d 表示什么？','rag')}><span className="suggestion-icon sand"><BookOpen size={23}/></span><strong>从知识里找答案</strong><p>查阅你的资料，让回答有据可循</p><ArrowUpRight size={17}/></button>
        </div><div className="welcome-footnote"><span/> 从一个小问题开始就好 <span/></div></div>:<div className="messages">{state.page?.next_before!=null&&<button className="copy-btn" disabled={state.loading} onClick={()=>void state.loadOlder()}>加载更早记录</button>}{messages.map(m=><article className={`message ${m.role}`} key={m.id}>{m.role==='assistant'&&<div className="assistant-label"><span className="mini-brand">jc</span>JC<span>{m.mode==='rag'?'来自你的知识库':'与你一起思考'}</span></div>}{m.role==='user'?<div className="user-bubble">{m.text}</div>:<Answer message={m} openCitation={setCitation}/>}</article>)}
          {busy&&<div className="processing" role="status"><LoaderCircle size={17} className="spin"/>正在处理，请稍候…</div>}
          {state.error&&<div className="request-error" role="alert"><p>{state.error}</p>{state.retryTarget&&<button onClick={()=>void send(true)} disabled={busy}>重新尝试</button>}</div>}<div ref={end}/></div>}
      </section>
      <footer className="composer-area"><div className="composer"><textarea ref={input} value={draft} onChange={e=>setDraft(e.target.value)} placeholder="有什么想法，尽管说说…" aria-label="输入问题" rows={2} maxLength={8000} disabled={busy||state.loading} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing&&e.keyCode!==229){e.preventDefault();void send();}}}/><div className="composer-tools"><div className="mode-switch" role="group" aria-label="回答模式"><button aria-pressed={mode==='rag'} onClick={()=>setMode('rag')} disabled={busy}><BookOpen size={14}/>知识库</button><button aria-pressed={mode==='chat'} onClick={()=>setMode('chat')} disabled={busy}><MessageSquare size={14}/>普通聊天</button></div><div className="send-tools"><span>Enter 发送</span><button className="send-button" aria-label="发送问题" onClick={()=>send()} disabled={!draft.trim()||busy||state.loading}>{busy?<LoaderCircle size={19} className="spin"/>:<ArrowUp size={21}/>}</button></div></div></div><p className="privacy-note">会话保存在此服务器，局域网访问设备共享；较早内容可能使用摘要</p></footer>
    </main>
    {citation&&<Modal title="参考原文" close={()=>setCitation(null)}><div className="citation-heading"><span className="file-icon"><FileText size={23}/></span><div><h3>{citation.filename}</h3><p>引用 [{citation.number}]{citation.metadata.page_number!=null?` · 第 ${citation.metadata.page_number} 页`:''}</p></div></div><div className="original-text">{citation.text}</div><div className="score-note">余弦相似度 {citation.score.toFixed(3)}<p>反映问题与片段的语义接近程度，不代表答案正确率。</p></div><CopyButton text={citation.text}/></Modal>}
    {panel==='summary'&&<Modal title="对话摘要" close={()=>setPanel(null)}><p className="drawer-intro">由模型整理，仅用于延续话题，可能有遗漏；完整原始对话仍可查看。</p><div className="original-text">{state.page?.conversation.summary}</div></Modal>}
    {panel==='upload'&&<Modal title="给想法，多一点资料" close={()=>setPanel(null)}><Documents/></Modal>}
  </div>;
}
