"use client";
import {useState} from "react";

const API = process.env.NEXT_PUBLIC_ERPA_API || "http://127.0.0.1:8000";
export default function Page() {
  const [message,setMessage]=useState("Morning brief.");
  const [result,setResult]=useState<any>(null);
  const [busy,setBusy]=useState(false);
  async function send(){setBusy(true);try{const r=await fetch(`${API}/api/mission_control/chat`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({thread_id:"vercel-demo",message})});setResult(await r.json());}finally{setBusy(false)}}
  return <main><p className="eyebrow">KATA / INTERNAL</p><h1>ERPA Mission Control</h1><p className="lede">Your catalogue, numbers and remembered decisions in one operational view.</p><section><textarea value={message} onChange={e=>setMessage(e.target.value)}/><button disabled={busy} onClick={send}>{busy?"Running graph…":"Send to ERPA"}</button></section>{result&&<article><pre>{result.answer}</pre><small>{result.trace?.cache_hit?"cache hit":"cache miss"} · {result.trace?.tokens} tokens · {result.trace?.latency_ms} ms</small></article>}</main>
}
