import fs from 'node:fs/promises';
import path from 'node:path';
import { Presentation, PresentationFile, FileBlob } from '@oai/artifact-tool';
import { finalizePresentation } from '/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations/container_tools/artifact_tool_utils.mjs';

const ROOT='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1';
const WORK=path.join(ROOT,'docs/presentation_20261018');
const BUILD=path.join(WORK,'build');
const SKILL='/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations';
const FONT='PingFang SC';
const C={bg:'#F8FAFD',ink:'#16243B',muted:'#53627A',blue:'#245BDD',violet:'#6852C7',pale:'#EAF0FC',green:'#176C5C',line:'#CED8E8',white:'#FFFFFF',dark:'#15233A'};
const p=Presentation.create({slideSize:{width:1280,height:720}});
const titles=[];
function text(s,t,x,y,w,h,size=27,color=C.ink,bold=false){
 const z=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 z.text=t;z.text.insets=0;z.text.style={fontSize:size,typeface:FONT,color,bold};return z;
}
function slide(title,notes='',dark=false){
 const s=p.slides.add();s.background.fill=dark?C.dark:C.bg;titles.push(title);
 text(s,title,64,48,1150,85,44,dark?C.white:C.ink,true);
 text(s,String(titles.length).padStart(2,'0'),1173,669,45,25,17,dark?'#C4D5F7':C.muted);
 s.speakerNotes.text='汇报截止：2026-10-18。工程实现、局部人工验收与研究效果分开表述。\n'+notes;
 return s;
}
function foot(s,t,dark=false){text(s,t,64,636,1080,42,18,dark?'#C4D5F7':C.muted);}
function node(s,t,x,y,w=220,h=84,color=C.blue){
 const z=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:C.white,line:{fill:color,width:2}});
 z.text=t;z.text.insets=10;z.text.style={fontSize:25,typeface:FONT,color:C.ink,bold:true,alignment:'center',verticalAlignment:'middle'};return z;
}
function link(s,a,b,from='right',to='left',label='',x=0,y=0){
 s.shapes.connect(a,b,{kind:from==='right'&&to==='left'?'straight':'elbow',fromSide:from,toSide:to,line:{fill:C.blue,width:2.5},tail:{type:'triangle',width:'med',length:'med'}});
 if(label)text(s,label,x,y,230,40,21,C.muted);
}
function table(s,v,{x=64,y=180,w=1152,h=390,widths,size=25}={}){
 const t=s.tables.add({rows:v.length,columns:v[0].length,left:x,top:y,width:w,height:h,values:v,...(widths?{columnWidths:widths}:{})});
 for(let r=0;r<v.length;r++)for(let c=0;c<v[0].length;c++){
  const a=t.getCell(r,c);a.fill=r===0?C.pale:r%2?C.white:'#F1F5FA';a.text.style={fontSize:size,typeface:FONT,color:r===0?C.blue:C.ink,bold:r===0};
 }
 t.borders.assign({fill:C.line,width:1,style:'solid'});return t;
}
function paragraphs(s,items,x=64,y=180,w=1100,gap=128){items.forEach(([h,b],i)=>{text(s,h,x,y+i*gap,w,42,30,C.blue,true);text(s,b,x,y+i*gap+49,w,74,25,C.muted);});}
async function image(s,file,x,y,w,h){const b=await fs.readFile(file);s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:path.basename(file),fit:'contain',position:{left:x,top:y,width:w,height:h}});}
const S={progress:'docs/项目进度与人工验收安排.md',core:'docs/MiMo统一核心使用与验收.md',real:'docs/validation/audio_core_20261017/README.md',hybrid:'docs/MiMo混合选角使用与验收.md',clone:'docs/MiMo参考音克隆接入与验收.md',tail:'docs/MiMo尾部重复检测与裁切.md',narration:'docs/validation/narration_identity_20261017/README.md',guard:'docs/validation/role_resplit_guard_20261018/README.md'};
function sources(...keys){return '本地来源：\n'+keys.map(k=>ROOT+'/'+(S[k]||k)).join('\n');}

// 01 封面
let s=slide('多角色有声书生成与质量控制',sources('progress','core'),true);
text(s,'项目进展与创新实现',64,205,1110,105,60,C.white,true);
text(s,'原文可追溯的角色编排\n面向黑盒 TTS 的资源受限修复',68,365,1100,128,32,'#D2DFF7');
text(s,'阶段汇报    2026 年 10 月 18 日',68,569,1100,42,24,'#C4D5F7');

// 02 产品界面
s=slide('项目目标与产品形态',sources('progress')+'\n图片：docs/presentation_build/assets/home.png，2026-10-12既有项目界面截图，仅展示产品形态，非最新控件验收。');
await image(s,path.join(ROOT,'docs/presentation_build/assets/home.png'),64,173,730,420);
paragraphs(s,[['面向长篇阅读','电子书解析、章节选择、\n旁白与人物分声。'],['面向制作返工','定位问题片段，保留原件，\n减少整章重复生成。']],835,184,380,190);
foot(s,'左图为 10 月 12 日既有界面实拍，新增工作流采用后续流程图说明');

// 03 能力进展
s=slide('目前已经实现的能力',sources('core','progress'));
table(s,[['处理阶段','已实现能力','当前范围'],['书籍与剧本','章节解析、人物与别名、原文区间','中英文文本，人工可纠正'],['声音编排','内置声音、固定描述、参考音克隆','角色参数与声音锁定'],['音频生产','持久缓存、PCM 组装、编码复检','统一核心仅接 MiMo'],['质量闭环','四维筛查、局部修复、报告与试听','规则策略及局部案例验证'],['网页工作流','章节选择、确认保护、资源库下载','后台链路已核验']],{y:174,h:400,widths:[200,540,412],size:25});
foot(s,'原有转换器支持多引擎；新统一核心与混合声音工作流本轮聚焦 MiMo');

// 04 全链路
s=slide('统一生成流程',sources('core','audiobook_generator/audio_core/pipeline.py'));
let a=node(s,'书籍原文\n章节与来源区间',64,195,235,94);
let b=node(s,'角色剧本\n归属与声音配置',368,195,235,94);
let c=node(s,'朗读计划\n规范化与分块',672,195,235,94);
let d=node(s,'MiMo 合成\n请求与原始样本',976,195,235,94);
link(s,a,b);link(s,b,c);link(s,c,d);
let e=node(s,'质量检查\n块、接缝、角色',976,405,235,94);
let f=node(s,'受限修复\n候选比较与复检',672,405,235,94);
let g=node(s,'章节输出\n音频与质量报告',368,405,235,94);
link(s,d,e,'bottom','top');link(s,e,f,'left','right');link(s,f,g,'left','right');
text(s,'原文映射、音频指纹和请求账本贯穿执行过程',64,555,1120,50,29,C.blue,true);
foot(s,'普通旁白与角色朗读复用同一核心，质量状态与文件生成状态分别记录');

// 05 创新关系
s=slide('创新点与实现层次',sources('core','progress','docs/论文创新点与实现方案.md'));
table(s,[['候选创新方向','具体解决的问题','实现基础'],['原文约束的角色编排','剧本改写、身份混淆、视角换章','来源区间、实体与叙述证据'],['资源受限的音频修复','重复、长停顿与无控制的返工','分层质检、请求账本、候选选择'],['面向辨识的混合选角','有限声音资源与相似角色混淆','共同探针、互动图、声音卡']],{y:190,h:310,widths:[320,416,416],size:26});
text(s,'共用基础：朗读规范化、跨块连续性、质量评估与证据记录',64,547,1130,65,29,C.blue,true);
foot(s,'这些是可研究的方法方向；新颖性和效果仍需相关工作对照与独立实验');

// 06 原文与叙述
s=slide('创新一：原文约束与叙述声音身份',sources('narration','audiobook_generator/role_script/validator.py'));
a=node(s,'本章原文\n稳定人物 ID',64,201,245,94);
b=node(s,'模型提出归属\n叙述或对白',390,201,245,94);
c=node(s,'本地校验\n逐字覆盖与引文',716,201,245,94);
link(s,a,b);link(s,b,c);
d=node(s,'人物自述与本人对白\n共用声音档案',716,399,430,94,C.green);link(s,c,d,'bottom','top');
text(s,'证据不足时保留默认旁白并提示复核',64,382,578,70,30,C.blue,true);
text(s,'每章独立判断叙述视角\n不把上一章的叙述者直接沿用到下一章',64,477,580,95,26,C.muted);
foot(s,'Flipped 两章已做真实文字诊断性复核；不能据此报告自动归属准确率');

// 07 双语规范化
s=slide('朗读规范化与内容比较',sources('core','audiobook_generator/audio_core/reading.py','audiobook_generator/audio_core/english_reading.py'));
table(s,[['层次','示例','实现原则'],['书籍原文','增长 3.5%','原文与来源位置保持不变'],['合成读法','增长百分之三点五','明确规则或用户词典，记录转换'],['内容核验','20 books / twenty books','有限等价比较，英文保留词界'],['歧义内容','编号、独立年份、专名','保留复核，避免擅自改写']],{y:190,h:330,widths:[210,450,492],size:26});
text(s,'中文按字计算 CER，英文按词计算 WER',64,553,1120,48,30,C.blue,true);
foot(s,'ASR 同字转写不能证明多音字读音正确；读法词典也不能代替实际试听');

// 08 选角
s=slide('创新二：角色互动图与混合选角',sources('hybrid','audiobook_generator/audio_core/casting.py'));
a=node(s,'角色 A',90,240,170,80);b=node(s,'角色 B',400,240,170,80);c=node(s,'角色 C',400,430,170,80);
link(s,a,b,'right','left');link(s,b,c,'bottom','top');
text(s,'频繁对话',272,191,180,36,23,C.blue,true);text(s,'互动频次形成边权',95,549,460,38,22,C.muted);
paragraphs(s,[['声音分配目标','优先拉开频繁互动角色的声音差异。'],['约束与资源','保留人工锁定，结合适配评分；\n内置声音不足时使用固定声音卡。'],['求解方法','小规模精确枚举，超限搜索回退。']],674,176,530,130);
foot(s,'图为方法示意，边权未填入实验数值；声纹距离只是听众混淆风险的代理');

// 09 声音路由
s=slide('三种声音模式的统一实现',sources('clone','hybrid','audiobook_generator/tts_providers/mimo_voice.py'));
table(s,[['模式','声音条件','路由与稳定性控制'],['内置声音','固定 voice 名称','tts，保留有效角色配置'],['声音设计','固定描述与表演指令','voicedesign，声音卡 ID 与版本'],['参考音克隆','参考 WAV 与 SHA256','voiceclone，核对实际参考字节']],{y:190,h:300,widths:[210,425,517],size:27});
a=node(s,'角色档案',103,540,245,68);b=node(s,'统一请求解析',514,540,245,68);c=node(s,'模型与缓存条件',925,540,245,68);link(s,a,b);link(s,b,c);
foot(s,'生成条件参考与质量比对参考分开管理；更换声音版本后不能沿用旧验收');

// 10 评估
s=slide('质量评估覆盖四个维度',sources('core','audiobook_generator/audio_core/quality.py'));
table(s,[['维度','实现方法','需要保留的判断边界'],['内容','SenseVoice 转写与编辑对齐','ASR 差异属于疑点，可能误报'],['拼接','端点、能量、频谱和实际停顿','重点检查已知接缝，规则待校准'],['一致性','ECAPA 声纹、音高与语速','短音频证据不足，情绪会影响指标'],['信号与编码','削波、静音、响度、解码复检','PCM 保留不等于听感已经通过']],{y:184,h:370,widths:[190,450,512],size:26});
foot(s,'状态分别记录 passed、failed、incomplete；缺失检查不会自动计为通过');

// 11 修复闭环
s=slide('创新三：资源受限的局部修复',sources('core','audiobook_generator/audio_core/store.py','audiobook_generator/audio_core/pipeline.py'));
a=node(s,'发现疑似问题',64,210,230,80);b=node(s,'选择本地处理\n或追加合成',385,210,230,80);c=node(s,'检查并预留额度',706,210,230,80);link(s,a,b);link(s,b,c);
d=node(s,'生成候选并复检\n本块与相邻接缝',706,400,350,90);link(s,c,d,'bottom','top');
e=node(s,'改善且无退化\n才采用候选',278,400,350,90,C.green);link(s,d,e,'left','right');
text(s,'限制请求次数、修复次数、追加字符数和运行时间',64,548,1150,46,29,C.blue,true);
foot(s,'当前为规则驱动策略，不计算实际金额；失败与进行中请求同样占用额度');

// 12 重复专项
s=slide('尾部重复的检测与安全裁切',sources('tail','audiobook_generator/audio_core/tail_repeat.py'));
table(s,[['证据检查','满足条件后的处理'],['完整转写显示正文后附加重复','寻找有限数量的低能量停顿切点'],['切点前正文完整，切点后仅重复','分别转写前后片段，保留比对证据'],['切点两侧各有 100 ms 保护','仅导出保留完整正文的 PCM 前缀']],{y:180,h:270,widths:[555,597],size:27});
a=node(s,'完整正文',100,504,480,79,C.green);b=node(s,'重复尾段',725,504,350,79,C.violet);link(s,a,b);
text(s,'安全切点',588,467,155,35,22,C.blue,true);
foot(s,'默认 review；严格条件加显式 auto 才可自动采用，短词或 ASR 歧义继续人工判断');

// 13 执行底座
s=slide('可追溯音频产物与安全组装',sources('core','audiobook_generator/audio_core/store.py','audiobook_generator/audio_core/audio.py'));
a=node(s,'实际请求\n模型、文本、声音',64,192,260,90);b=node(s,'原始音频缓存\n内容指纹',510,192,260,90);c=node(s,'本地渲染产物\n操作与参数',956,192,260,90);link(s,a,b);link(s,b,c);
d=node(s,'PCM 顺序组装\n实际样本时间表',956,412,260,90);e=node(s,'最终编码复检\n音频与报告绑定',510,412,260,90);link(s,c,d,'bottom','top');link(s,d,e,'left','right');
text(s,'每次重采样形成独立样本\n本地变速复用原始音频\n候选、原件和人工裁决分别保存',64,398,410,150,27,C.muted);
foot(s,'样本数、顺序与 SHA256 保证证据对应；同参数缓存复用不冒充新的独立生成');

// 14 实际章
s=slide('真实案例：《Flipped》首章',sources('real','progress'));
[['14,311','原文字符'],['5','角色'],['100','朗读块'],['99','接缝']].forEach(([v,l],i)=>{text(s,v,64+i*300,191,280,90,61,C.blue,true);text(s,l,67+i*300,294,270,45,27,C.muted);});
table(s,[['阶段','实际完成内容'],['首次整章','完成约 15 分 32 秒原始版本，保留原音频'],['克隆扩展','67 次新请求，Bryce 参考音克隆'],['局部修订','重复、停顿与发音重启处理，最新候选约 17 分 34 秒']],{y:393,h:205,widths:[220,932],size:25});
foot(s,'不同声音版本的时长不能直接比较质量；局部接受不代表整章或整书全部验收');

// 15 真实修复
s=slide('已接受的局部修复案例',sources('real','tail'));
table(s,[['实际问题','处理方法','验证与接受范围'],['R039 读完后重复','保留完整前缀，移除异常尾段','保留语音 PCM 不变，局部试听接受'],['R018 多次 No','保留原文要求的三次 No','前后分段核验，局部试听接受'],['J076 停顿过长','移除已确认静音中央部分','新上下文约 1 秒，试听接受'],['R034 发音重启','C’mon 展开为 Come on!','单次追加合成，发音与接缝接受']],{y:180,h:350,widths:[260,430,462],size:25});
text(s,'已归档 10 个接受案例，全部来自同书同章',64,560,1150,45,31,C.blue,true);
foot(s,'回顾案例具有来源依赖，不据此计算无偏成功率或声称跨书籍泛化');

// 16 人工复核
s=slide('集中复核与听众辨识材料',sources('progress','real','audiobook_generator/audio_core/review_queue.py'));
a=node(s,'133 条机器提示',64,192,265,85);b=node(s,'48 个定位窗口',485,192,265,85);c=node(s,'9 段不重叠路线',906,192,310,85);link(s,a,b);link(s,b,c);
text(s,'保留全部诊断，合并重叠上下文，减少同一音频反复试听',64,332,1150,60,31,C.blue,true);
paragraphs(s,[['复核安排','默认路线累计 973.04 秒；原重叠窗口累计 1629.20 秒。'],['辨识先导','36 题已导出，九章材料质量预审通过，尚无真实辨识答案。']],64,425,1150,94);
foot(s,'本批互动图与随机分配相同，不能据此报告两者效果差异；播放器浏览器验收待完成');

// 17 网页工作流
s=slide('网页工作流的状态与并发保护',sources('guard','docs/validation/webui_spawn_workflow_20261017/README.md'));
a=node(s,'上传书籍\n按章选择',64,202,235,90);b=node(s,'拆分中\n旧确认立即作废',368,202,235,90);c=node(s,'核对声音与归属\n重新确认',672,202,235,90);d=node(s,'生成与下载\n报告和资源库',976,202,235,90);link(s,a,b);link(s,b,c);link(s,c,d);
text(s,'同一书籍的保存、确认与生成启动共享操作锁',64,389,1140,49,32,C.blue,true);
text(s,'拆分期间拒绝旧确认启动；远端请求期间不持锁\n关闭反馈流不会提前释放仍在工作的线程\n后台真实 spawn 与本机 SDK 替身覆盖成功、缓存和失败分支',64,466,1135,126,27,C.muted);
foot(s,'这是源码与后台链路验证；新增控件的浏览器视觉及真实操作体验仍待验收');

// 18 范围与推进
s=slide('当前成果与后续重点',sources('progress','guard','core'));
table(s,[['层次','目前成果','下一步'],['工程核心','统一管线、角色声音、质检与局部修复','稳定 MiMo 网页上传、确认、生成和下载'],['真实案例','Flipped 首章、局部接受与声音小试','集中完成冻结版本核验，扩大实际使用'],['研究准备','36 题先导、标注与边界训练入口','独立来源、阈值校准与听众辨识实验'],['适配范围','原转换器多引擎，统一核心仅 MiMo','Qwen TTS／VoxCPM 适配暂缓']],{y:177,h:346,widths:[175,520,457],size:25});
text(s,'最新保存回归：674 项，644 通过，30 项环境跳过',64,552,1150,45,29,C.blue,true);
foot(s,'研究实验与新引擎适配当前暂缓；工程测试数量不能替代缺陷检出率或听众收益');

await fs.writeFile(path.join(BUILD,'slide_outline.json'),JSON.stringify(titles,null,2));
const candidate=path.join(BUILD,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
console.log('DRAFT',candidate,'SLIDES',titles.length);
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(BUILD,'renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
 console.log('RENDER',i+1);
}
const result=await finalizePresentation({workspaceDir:WORK,candidatePath:candidate,finalPath:path.join(WORK,'output','多角色有声书_项目进展与创新实现_20261018.pptx'),pythonExecutable:'/Users/yinzh/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,5,7,9,10,12,14,15,18].flatMap(n=>['--require-native-table-slide',String(n)])],requiredNativeTableOwnerSlides:[3,5,7,9,10,12,14,15,18],requiredNativeChartOwnerSlides:[],fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:path.join(BUILD,'validation.json')});
console.log('FINAL',JSON.stringify(result));
