/** Render the captured demo frames as a short, moving browser-native video.
 *
 * Use this when ffmpeg is unavailable:
 *   node scripts/render_demo_video.mjs
 */
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const demo = path.join(root, "demo");
const frames = ["01-index.png", "02-filtered.png", "03-decision-graph.png", "04-review-result.png"];
const browserCandidates = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
];
const output = path.join(demo, "gatewise-demo.mp4");

const html = `<!doctype html><meta charset="utf-8"><title>Rendering Gatewise demo</title>
<style>html,body{margin:0;background:#171713}canvas{width:2880px;height:1800px}</style>
<canvas id="c" width="2880" height="1800"></canvas><pre id="status">Loading frames…</pre>
<script>
const names=${JSON.stringify(frames)};
const scenes=[5000,3500,5500,6000];
const canvas=document.querySelector('#c'),ctx=canvas.getContext('2d',{alpha:false});
const status=document.querySelector('#status');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(){
 const images=await Promise.all(names.map(src=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src='/image/'+src;})));
 const candidates=['video/mp4;codecs=avc1.42E01E','video/mp4','video/webm;codecs=vp9','video/webm;codecs=vp8'];
 const mime=candidates.find(type=>MediaRecorder.isTypeSupported(type));
 if(!mime)throw Error('This browser cannot record MP4 or WebM.');
 status.textContent='Rendering '+mime+'…';
 const stream=canvas.captureStream(30),chunks=[];
 const recorder=new MediaRecorder(stream,{mimeType:mime,videoBitsPerSecond:2000000});
 recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
 let stopped;const finished=new Promise((resolve,reject)=>{stopped=resolve;recorder.onerror=e=>reject(e.error||e)});
 recorder.onstop=stopped;recorder.start(250);
  const total=scenes.reduce((a,b)=>a+b,0),start=performance.now(),fps=30;
  function paint(now){
  const rawElapsed=now-start,elapsed=Math.min(rawElapsed,total-1),index=scenes.findIndex((d,i)=>elapsed<scenes.slice(0,i+1).reduce((a,b)=>a+b,0));
  let offset=elapsed-scenes.slice(0,index).reduce((a,b)=>a+b,0),duration=scenes[index],image=images[index];
  ctx.fillStyle='#171713';ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.drawImage(image,0,0,canvas.width,canvas.height);
  if(rawElapsed<total){setTimeout(()=>requestAnimationFrame(paint),1000/fps)}else{setTimeout(()=>recorder.stop(),150)}
 }
 requestAnimationFrame(paint);await finished;stream.getTracks().forEach(track=>track.stop());
 const blob=new Blob(chunks,{type:mime});
 const response=await fetch('/upload?mime='+encodeURIComponent(mime),{method:'POST',body:blob});
 if(!response.ok)throw Error(await response.text());
 status.textContent='Done';document.title='Demo rendered';
}
run().catch(error=>{status.textContent='ERROR: '+error.message;document.title='Render failed';fetch('/error',{method:'POST',body:error.stack||error.message})});
</script>`;

for (const name of frames) await stat(path.join(demo, name));
let savedPath;
let savedMime;
let failure;
const requests = [];
const server = createServer(async (request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  requests.push(`${request.method} ${url.pathname}`);
  if (request.method === "GET" && url.pathname === "/") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); response.end(html); return;
  }
  if (request.method === "GET" && url.pathname.startsWith("/image/")) {
    const name = path.basename(url.pathname.slice(7));
    if (!frames.includes(name)) { response.writeHead(404).end(); return; }
    response.writeHead(200, { "Content-Type": "image/png", "Cache-Control": "no-store" });
    response.end(await readFile(path.join(demo, name))); return;
  }
  if (request.method === "POST" && url.pathname === "/upload") {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    savedMime = url.searchParams.get("mime") || "";
    const extension = savedMime.includes("mp4") ? "mp4" : "webm";
    savedPath = path.join(demo, `gatewise-demo.${extension}`);
    await writeFile(savedPath, Buffer.concat(chunks));
    response.writeHead(200).end("saved"); return;
  }
  if (request.method === "POST" && url.pathname === "/error") {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    failure = Buffer.concat(chunks).toString(); response.writeHead(200).end(); return;
  }
  response.writeHead(404).end();
});

await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const { port } = server.address();
let browserPath;
for (const candidate of browserCandidates) {
  try { await stat(candidate); browserPath = candidate; break; } catch {}
}
if (!browserPath) throw Error("Chrome or Edge was not found in the standard install locations.");
const profile = await mkdtemp(path.join(tmpdir(), "gatewise-render-"));
try {
  const browser = spawn(browserPath, [
    "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
    "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
    `--user-data-dir=${profile}`, `http://127.0.0.1:${port}/`,
  ], { stdio: ["ignore", "ignore", "pipe"], windowsHide: true });
  let browserLog = "";
  browser.stderr.on("data", chunk => { browserLog += chunk.toString(); });
  const deadline = Date.now() + 45_000;
  while (!savedPath && !failure && Date.now() < deadline) {
    if (browser.exitCode !== null) break;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  browser.kill();
  if (failure) throw Error(failure);
  if (!savedPath) throw Error(`Browser renderer did not return a video within 45 seconds. Requests: ${requests.join(", ") || "none"}. ${browserLog}`);
  console.log(`wrote ${savedPath}`);
  console.log(`mime ${savedMime}; duration about 11.4s; size ${(await stat(savedPath)).size / 1048576 | 0} MiB`);
} finally {
  server.close();
  const resolved = path.resolve(profile), tempRoot = path.resolve(tmpdir()) + path.sep;
  if (!resolved.startsWith(tempRoot)) throw Error("Refusing to remove a path outside the temporary directory.");
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 250 }).catch(() => {});
}
