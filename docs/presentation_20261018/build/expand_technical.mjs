import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
import {finalizePresentation} from '/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations/container_tools/artifact_tool_utils.mjs';

const ROOT='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1';
const WORK=path.join(ROOT,'docs/presentation_20261018');
const BUILD=path.join(WORK,'build/technical_revision');
const SKILL='/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations';
const SOURCE=path.join(WORK,'output/多角色有声书_项目进展与创新实现_20261018.pptx');
const FINAL=path.join(WORK,'output/多角色有声书_项目进展与创新实现_技术原理详解版_20261018.pptx');
await fs.mkdir(BUILD,{recursive:true});
await fs.mkdir(path.join(BUILD,'final_renders'),{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const original=[...p.slides.items];
const FONT='PingFang SC';
const C={bg:'#F8FAFD',ink:'#16243B',muted:'#53627A',blue:'#245BDD',green:'#176C5C',line:'#CED8E8',white:'#FFFFFF'};
function text(s,t,x,y,w,h,size=27,color=C.ink,bold=false){
 const z=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 z.text=t;z.text.insets=0;z.text.style={fontSize:size,typeface:FONT,color,bold};return z;
}
function slide(title,files,notes){
 const s=p.slides.add();s.background.fill=C.bg;
 text(s,title,64,48,1150,85,44,C.ink,true);
 text(s,'00',1173,669,45,25,17,C.muted);
 s.speakerNotes.text='汇报截止：2026-10-18。技术补充基于项目现有代码，公式归纳当前实现，未经独立实验验证的效果不作结论。\n'+notes+'\n本地来源：\n'+files.map(f=>ROOT+'/'+f).join('\n');
 return s;
}
function foot(s,t){text(s,t,64,636,1090,42,18,C.muted);}
function node(s,t,x,y,w=250,h=90,color=C.blue){
 const z=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:C.white,line:{fill:color,width:2}});
 z.text=t;z.text.insets=10;z.text.style={fontSize:25,typeface:FONT,color:C.ink,bold:true,alignment:'center',verticalAlignment:'middle'};return z;
}
function link(s,a,b,from='right',to='left'){
 s.shapes.connect(a,b,{kind:from==='right'&&to==='left'?'straight':'elbow',fromSide:from,toSide:to,line:{fill:C.blue,width:2.5},tail:{type:'triangle',width:'med',length:'med'}});
}
function headbody(s,h,b,x,y,w=1100){text(s,h,x,y,w,42,29,C.blue,true);text(s,b,x,y+48,w,92,25,C.muted);}

const source=slide('技术原理：原文区间与身份约束',[
 'audiobook_generator/role_script/validator.py','docs/validation/narration_identity_20261017/README.md'
],'S 表示本章原文。source_span 使用半开区间 [start,end)。严格来源校验要求切片内容与分段完全一致、区间连续且覆盖全章。角色归属的引文同样需要切片验证。该机制保证结构与引文可追溯，不能保证模型对说话人语义判断必然正确。');
text(source,'分段文本 = S[start:end]     相邻分段 end = 下一段 start',64,174,1150,58,31,C.blue,true);
let a=node(source,'模型输出\n文本区间与人物 ID',64,280,290,96);
let b=node(source,'本地校验\n完整覆盖与引文匹配',495,280,290,96);
let c=node(source,'声音解析\n人物 ID 绑定档案',926,280,290,96);link(source,a,b);link(source,b,c);
headbody(source,'叙述身份与声音配置分开保存','每章单独记录叙述者及原文证据。确认人物自述后，让叙述与该人物对白复用同一声音档案。',64,429);
foot(source,'区间覆盖可发现增删或错位；说话人语义仍需证据与人工复核');

const probes=slide('技术原理：共同探针与声音距离',[
 'audiobook_generator/audio_core/casting.py','docs/MiMo混合选角使用与验收.md'
],'每个声音至少具有两条共同探针，先核验合成结果再允许进入声音库。对相同文本分别比较两种声音的声纹向量，计算余弦距离。跨文本汇总采用均值减0.25倍标准差，并截断为非负值。常数为当前实现值，不代表最优超参数。');
a=node(probes,'相同探针文本\n每种声音都朗读',64,179,290,92);
b=node(probes,'核验探针音频\n提取声纹向量 e',495,179,290,92);
c=node(probes,'逐文本比较\n再汇总跨文本距离',926,179,290,92);link(probes,a,b);link(probes,b,c);
text(probes,'单条探针：dₖ = 1 − cos(eᵤₖ, eᵥₖ)',64,330,1140,52,33,C.blue,true);
text(probes,'声音距离：d(u,v) = max(0, mean(dₖ) − 0.25 × std(dₖ))',64,410,1150,58,30,C.ink,true);
text(probes,'相同文本减少语言内容差异的干扰。\n跨文本距离波动越大，扣减越多，优先保留稳定的声音区分。',64,506,1140,85,27,C.muted);
foot(probes,'至少两条共同探针且 verified=true；声纹距离属于混淆风险代理，需听众实验验证');

const optimization=slide('技术原理：互动图选角的目标函数',[
 'audiobook_generator/audio_core/casting.py'
],'w_ij 是角色 i、j 连续对话切换次数，旁白或至少1.5秒停顿会断开链条。f(i) 是分配的声音，P 是人工审查的角色适配惩罚，M 是相对初始分配的换声数。目标函数系数0.25、0.1、0.05是代码当前配置。完整候选空间不超过4096时精确枚举，否则按加权度贪心并最多20轮局部改配或交换。');
text(optimization,'最小化 J(f) = Σ wᵢⱼ × exp(−d(f(i),f(j)) / 0.25)',64,176,1150,58,31,C.blue,true);
text(optimization,'                         + 0.1 × Σ P(i,f(i)) + 0.05 × M(f)',64,239,1150,55,30,C.blue,true);
headbody(optimization,'互动权重决定优先级','相邻角色轮换累计边权。频繁对话的角色若声音接近，会产生更大的混淆惩罚。',64,337,1110);
headbody(optimization,'硬约束与搜索范围','锁定声音必须保留，可启用旁白独占和声音不复用。\n分配方案数 ≤4096 时枚举，超限采用贪心及局部交换。',64,474,1110);
foot(optimization,'f 为角色到声音的映射，P 为适配惩罚，M 为换声数；最优性只针对当前代理目标');

const quality=slide('技术原理：异常指标与接缝上下文',[
 'audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/boundary_model.py'
],'内容对齐采用动态规划编辑距离，中文按字、英文按词。S/D/I/N分别为替换/删除/插入/参考单位数。声纹漂移比较当前音频与角色参考，不同于选角阶段跨声音探针比较。接缝使用端点跳变、RMS差、频谱距离、语音端点、两侧静音、计划停顿和是否同一说话人共9维特征。可选多标签逻辑模型接口已实现，但本页不声称已得到真实数据泛化收益。');
headbody(quality,'内容缺陷定位','CER / WER = (S + D + I) / N\n转写后对齐到参考文本，分别定位替换、漏读和多读。',64,174,1100);
headbody(quality,'声音一致性筛查','声纹漂移 = 1 − cos(e当前, e参考)\n结合音高偏移与语速变化提示复核，短音频证据不足时保留未完成状态。',64,322,1100);
a=node(quality,'左块尾部',64,510,235,80);b=node(quality,'已知接缝\n9 维声学特征',424,510,300,80);c=node(quality,'右块开头',849,510,235,80);link(quality,a,b);link(quality,b,c);
foot(quality,'S/D/I 为替换/删除/插入，N 为参考字词数；ASR 与启发式阈值仅提供疑点证据');

const budget=slide('技术原理：请求账本与资源预留',[
 'audiobook_generator/audio_core/store.py','audiobook_generator/audio_core/pipeline.py','audiobook_generator/audio_core/repair.py'
],'ArtifactStore使用SQLite。reserve在BEGIN IMMEDIATE事务内读取本次run的全部请求记录并检查次数、追加字符与已用时间，再插入running记录。失败与未完成记录也计入消耗，settle只更新状态。时间上限是请求发起前及修复前的检查，不宣称是操作系统级实时硬截止。');
text(budget,'资源状态 B =（总请求数，修复请求数，修复字符数，已用时间）',64,174,1150,58,29,C.blue,true);
a=node(budget,'追加合成动作\n重采样或内容修复',64,282,290,96);
b=node(budget,'SQLite 事务内\n检查额度并登记 running',495,282,290,96);
c=node(budget,'调用黑盒 TTS\n回填成功或失败',926,282,290,96);link(budget,a,b);link(budget,b,c);
headbody(budget,'预留机制防止重复重试绕过限制','请求发出前先记账，失败和未完成请求同样占用次数。\n追加合成还要检查修复字符额度与单块重试上限。',64,431,1110);
foot(budget,'本地动作另有限次控制；时间在执行前检查，资源统计尚未折算为实际金额');

const acceptance=slide('技术原理：候选比较与无退化约束',[
 'audiobook_generator/audio_core/pipeline.py','audiobook_generator/audio_core/quality.py'
],'对应pipeline.preserves_checks与attempt_repair。复检范围是目标分块和左右相邻接缝。候选不能新增已确认严重错误，原passed维度仍须passed，已有内容对齐误差不能增加。随后对本块与边界报告的rank各分量求和，按Python元组字典序比较，只有严格改善才采用。重分块候选还必须通过内部接缝的内容与信号检查。');
a=node(acceptance,'左邻块',64,174,235,80);b=node(acceptance,'修复候选',424,174,300,80,C.green);c=node(acceptance,'右邻块',849,174,235,80);link(acceptance,a,b);link(acceptance,b,c);
headbody(acceptance,'第一步：本块与两侧接缝共同复检','不增加已确认严重错误，保住原已通过维度，内容对齐误差不升高。\n重分块还要检查新产生的内部接缝。',64,313,1110);
headbody(acceptance,'第二步：按优先级严格比较','累计报告按严重错误、接缝、一致性、内容、信号及误差排序。\n只有无退化且排序改善才替换，否则保留原件与候选记录。',64,463,1110);
foot(acceptance,'检查保证依赖当前检测覆盖范围；机器规则改善仍需局部试听及最终人工验收');

const after=new Map([[6,[source]],[8,[probes,optimization]],[10,[quality]],[11,[budget,acceptance]]]);
const order=[];
for(let i=0;i<original.length;i++){order.push(original[i]);order.push(...(after.get(i+1)||[]));}
for(let i=0;i<order.length;i++)order[i].moveTo(i);
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i];
 for(const shape of s.shapes.items){
  if(Math.abs(shape.position.left-1173)<1 && Math.abs(shape.position.top-669)<1){shape.text=String(i+1).padStart(2,'0');}
 }
}
const inspect=await p.inspect({select:'$.slides[*]',include:['id','index','title','elements.text','elements.kind']});
await fs.writeFile(path.join(BUILD,'content.ndjson'),inspect.ndjson);
const tables=p.slides.items.flatMap((s,i)=>s.tables.items.length?[i+1]:[]);
const candidate=path.join(BUILD,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
console.log('CANDIDATE',p.slides.items.length,'TABLES',tables);
const result=await finalizePresentation({workspaceDir:WORK,candidatePath:candidate,finalPath:FINAL,
 pythonExecutable:'/Users/yinzh/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'reference',families:[FONT],referencePath:SOURCE,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:path.join(BUILD,'validation_v2.json')});
console.log('FINAL',JSON.stringify(result));
const final=await PresentationFile.importPptx(await FileBlob.load(FINAL));
for(let i=0;i<final.slides.items.length;i++){
 const png=await final.export({slide:final.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(BUILD,'final_renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log('RENDER',i+1);
}
