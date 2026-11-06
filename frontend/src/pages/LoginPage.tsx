import { type FormEvent, useState } from "react";
import { useLogin } from "@/api/hooks";
import { Button, inputClass } from "@/components/ui";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [register, setRegister] = useState(false);
  const login = useLogin();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password, register });
  };
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-2xl border border-line bg-surface p-8">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <h1 className="text-xl font-semibold">Lodestar</h1>
        </div>
        <p className="text-sm text-ink-2">{register ? "Create the owner account (first run only)." : "Sign in to your research workspace."}</p>
        <input className={inputClass} type="email" autoComplete="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input
          className={inputClass}
          type="password"
          autoComplete={register ? "new-password" : "current-password"}
          placeholder={register ? "Password (12+ characters)" : "Password"}
          minLength={register ? 12 : 1}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {login.isError && <p className="text-sm text-critical" role="alert">{login.error.message}</p>}
        <Button type="submit" className="w-full" disabled={login.isPending}>{register ? "Create account" : "Sign in"}</Button>
        <button type="button" onClick={() => setRegister(!register)} className="w-full text-xs text-ink-2 hover:text-ink">
          {register ? "Already set up? Sign in" : "First time? Create the owner account"}
        </button>
      </form>
    </div>
  );
}
