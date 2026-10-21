"use strict";
// Tokens live only in memory. sessionStorage holds only the one-use PKCE transaction.
window.AquaAuth = (() => {
  const cfg = window.AQUACLOUD_AUTH;
  const key = "aquacloud.pkce";
  let accessToken = "", expiresAt = 0, groups = [];
  const b64 = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const random = () => b64(crypto.getRandomValues(new Uint8Array(32)));
  const configured = () => !!(cfg?.domain && cfg?.clientId);
  function domain() {
    const url = new URL(cfg.domain);
    if (url.protocol !== "https:" || url.pathname !== "/" || url.search || url.hash || url.username || url.password) throw new Error("Invalid Cognito domain.");
    return url.origin;
  }
  function clear() { accessToken = ""; expiresAt = 0; groups = []; }
  function signedIn() { return !!accessToken && Date.now() < expiresAt; }
  async function login() {
    if (!configured()) throw new Error("Cognito deployment configuration is pending.");
    const verifier = random(), state = random();
    const challenge = b64(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
    sessionStorage.setItem(key, JSON.stringify({verifier, state, created: Date.now()}));
    const params = new URLSearchParams({response_type:"code", client_id:cfg.clientId, redirect_uri:cfg.redirectUri, scope:cfg.scopes, state, code_challenge:challenge, code_challenge_method:"S256"});
    location.assign(`${domain()}/oauth2/authorize?${params}`);
  }
  async function initialize() {
    const params = new URLSearchParams(location.search);
    if (!params.has("code") && !params.has("error")) return;
    const saved = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    history.replaceState({}, "", location.pathname);
    let txn;
    try { txn = JSON.parse(saved); } catch { throw new Error("Invalid login transaction."); }
    if (!txn || !params.get("state") || txn.state !== params.get("state") || Date.now()-txn.created > 600000 || Date.now() < txn.created) throw new Error("Login expired or state did not match. Sign in again.");
    if (params.has("error")) throw new Error("Cognito sign-in was cancelled or rejected.");
    const response = await fetch(`${domain()}/oauth2/token`, {method:"POST", redirect:"error", credentials:"omit", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body:new URLSearchParams({grant_type:"authorization_code", client_id:cfg.clientId, redirect_uri:cfg.redirectUri, code:params.get("code"), code_verifier:txn.verifier})});
    if (!response.ok) throw new Error("Login code exchange failed. Sign in again.");
    const tokens = await response.json();
    if (tokens.token_type?.toLowerCase() !== "bearer" || !tokens.access_token || !Number.isFinite(tokens.expires_in) || tokens.expires_in <= 0) throw new Error("Invalid token response.");
    // Decoded groups control presentation only. API Gateway and Lambda enforce access.
    const part = tokens.access_token.split(".")[1].replace(/-/g,"+").replace(/_/g,"/");
    const claims = JSON.parse(atob(part));
    if (claims.token_use !== "access" || claims.client_id !== cfg.clientId) throw new Error("Unexpected access token.");
    groups = Array.isArray(claims["cognito:groups"]) ? claims["cognito:groups"] : [];
    expiresAt = Math.min(Date.now() + tokens.expires_in*1000, Number(claims.exp)*1000) - 30000;
    accessToken = tokens.access_token;
    if (!signedIn()) { clear(); throw new Error("Access token expired."); }
  }
  function headers(apiUrl) {
    if (apiUrl !== cfg.apiUrl.replace(/\/+$/, "")) throw new Error("API URL does not match the trusted deployment. No token was sent.");
    if (!signedIn()) { clear(); throw new Error("Sign in to access AquaCloud."); }
    return {Authorization:`Bearer ${accessToken}`};
  }
  function logout() {
    clear(); sessionStorage.removeItem(key);
    location.assign(`${domain()}/logout?${new URLSearchParams({client_id:cfg.clientId,logout_uri:cfg.logoutUri})}`);
  }
  return {configured, login, initialize, headers, logout, clear, signedIn, canExport:()=>signedIn() && groups.some(g=>["Operator","Admin"].includes(g)), role:()=>groups.filter(g=>["Viewer","Operator","Admin"].includes(g)).join(", ") || "No assigned role"};
})();
