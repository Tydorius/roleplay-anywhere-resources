// 1.0's own sight code, copied from the bundle (index-BrLojUrw.js): runInContext'd under the
// loader with the real `line-of-sight` and `sight-blockers` patches, so the tests exercise
// the game's real line-of-sight walk, not a stand-in. Np (natural-shape masks) and DN
// ("someone holds this door open", here an entity flag) are test stand-ins.
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { PATCHES } from '../patch.mjs';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

export const SIGHT_1_0 =
  'function S1(e,t){return t[0]>e[0]?"e":t[0]<e[0]?"w":t[1]>e[1]?"n":"s"}' +
  'function xh(e,t,n){const[i,o]=Qe(e,t)?[t,n]:[n,t],g=S1(i,o);return e.openings.some(r=>r[0]===i[0]&&r[1]===i[1]&&r[2]===g)}' +
  'function Qe(e,t){const n=t[0]>=e.position[0]&&t[1]>=e.position[1]&&t[0]<e.position[0]+e.size[0]&&t[1]<e.position[1]+e.size[1];if(!n||!e.shape)return n;const i=Np(e);return!i||i[Math.floor(t[1]-e.position[1])*e.size[0]+Math.floor(t[0]-e.position[0])]===1}' +
  'function AN(e,t,n){for(const i of e)if(Qe(i,t)!==Qe(i,n)&&!xh(i,t,n))return!0;return!1}' +
  'function ife(e){return e.regions.filter(t=>t.wall)}' +
  'function T1(e,t){const n=e[0]<t[0]||e[1]<t[1]?e:t;return`${n[0]},${n[1]},${e[0]!==t[0]?"x":"y"}`}' +
  'function yN(e,t,n){return xN(e,t,n)>=1}' +
  'function xN(e,t,{walls:n,shut:i}){if(n.length===0)return 1;let o=Math.floor(e[0]),g=Math.floor(e[1]);const r=Math.floor(t[0]),m=Math.floor(t[1]),s=t[0]-e[0],a=t[1]-e[1],p=Math.sign(s),u=Math.sign(a),c=p?Math.abs(1/s):1/0,h=u?Math.abs(1/a):1/0;let l=p>0?(o+1-e[0])*c:p<0?(e[0]-o)*c:1/0,d=u>0?(g+1-e[1])*h:u<0?(e[1]-g)*h:1/0;for(let A=0;(o!==r||g!==m)&&A<4096;A++){const f=[o,g];let v;l<d?(v=l,o+=p,l+=c):(v=d,g+=u,d+=h);const y=[o,g];if(AN(n,f,y)||i.size>0&&i.has(T1(f,y)))return Math.min(v,1-1e-9)}return 1}' +
  'function sr(e){var t;return e.type==="object"&&!!((t=e.objectTemplate)!=null&&t.door)}' +
  'const Whe={door:!0,bars:!1,gate:!1,curtain:!0};' +
  'function Fp(e){const[t,n]=e.pos;return e.size[0]===0?[[t-1,n],[t,n]]:[[t,n-1],[t,n]]}' +
  'function Ob(e){const t=new Set;for(const n of e.entities){if(!sr(n)||n.dead||!Whe[n.objectTemplate.door]||DN(e,n))continue;const[i,o]=Fp(n);t.add(T1(i,o))}return{walls:ife(e),shut:t}}' +
  'function Np(){return null}function DN(e,t){return!!t.heldOpen}';

// A vm context with the loader, 1.0's sight code (patched with the real patches), and each
// file in `files` (paths relative to tools/code-mod-loader) run into it, in that order.
export function loadWithSight(files) {
  const ctx = vm.createContext({ console: { info() {}, error() {}, warn() {} } });
  ctx.globalThis = ctx;
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'runtime/loader.js'), 'utf8'), ctx, { filename: 'runtime/loader.js' });
  let sight = SIGHT_1_0;
  for (const name of ['line-of-sight', 'sight-blockers']) {
    const p = PATCHES.find(q => q.name === name);
    assert.equal([...sight.matchAll(p.find)].length, 1, `${name} matches the 1.0 sight code`);
    sight = sight.replace(p.find, p.replace);
  }
  vm.runInContext(sight, ctx, { filename: 'game-1.0-sight' });
  for (const f of files) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  return ctx;
}
