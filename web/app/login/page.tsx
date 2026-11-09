"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState("soban@kodoai.xyz");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  async function link() {
    setErr(""); setMsg("");
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { shouldCreateUser: false, emailRedirectTo: `${window.location.origin}/leads` },
    });
    if (error) setErr(error.message); else setMsg("Check your inbox for the sign-in link.");
  }
  async function pw() {
    setErr(""); setMsg("");
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) setErr(error.message); else router.replace("/leads");
  }

  return (
    <div className="card" style={{ maxWidth: 420, margin: "40px auto" }}>
      <h1>Sign in</h1>
      <p className="muted">Single operator. Only the operator's email can read or write data.</p>
      <div className="bar"><input style={{ flex: 1 }} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email" /></div>
      <div className="bar"><button className="primary" onClick={link}>Email me a sign-in link</button></div>
      <p className="muted">Or, if you set a password in Supabase:</p>
      <div className="bar">
        <input style={{ flex: 1 }} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" />
        <button onClick={pw} disabled={!password}>Sign in</button>
      </div>
      {msg && <p className="msg">{msg}</p>}
      {err && <p className="err">{err}</p>}
    </div>
  );
}
