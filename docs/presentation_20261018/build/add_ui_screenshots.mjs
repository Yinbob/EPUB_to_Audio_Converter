import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
import {finalizePresentation} from '/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations/container_tools/artifact_tool_utils.mjs';

const ROOT='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1';
const WORK=path.join(ROOT,'docs/presentation_20261018');
const BUILD=path.join(WORK,'build/ui_revision');
const ASSETS=path.join(WORK,'assets/ui_20261018');
const SOURCE=path.join(WORK,'output/多角色有声书_音频检查技术详解_20261018.pptx');
const FINAL=path.join(WORK,'output/多角色有声书_功能界面与技术讲解_20261018.pptx');
const SKILL='/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations';
const FONT='PingFang SC';
const C={bg:'#F8FAFD',ink:'#16243B',muted:'#53627A',blue:'#245BDD'};
await fs.mkdir(path.join(BUILD,'final_renders'),{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const before=await p.inspect({select:'$.slides[*]',include:['id','index','title','elements.id','elements.kind','elements.text','elements.position']});
await fs.writeFile(path.join(BUILD,'before.ndjson'),before.ndjson);
const original=[...p.slides.items];
function text(s,t,x,y,w,h,size=27,color=C.ink,bold=false){
 const z=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 z.text=t; z.text.insets=0; z.text.style={fontSize:size,typeface:FONT,color,bold};return z;
}
async function shot(s,file,region,frame,alt){
 const [x,y,w,h]=region;
 s.images.add({blob:await fs.readFile(path.join(ASSETS,file)),contentType:'image/jpeg',alt,fit:'cover',
  crop:{left:x/825,top:y/957,right:(825-x-w)/825,bottom:(957-y-h)/957},position:frame});
}
function block(s,h,b,y,x=850,w=366){text(s,h,x,y,w,42,29,C.blue,true);text(s,b,x,y+48,w,115,27,C.muted);}
function foot(s,t){text(s,t,64,643,1090,40,18,C.muted);}
function note(s,t,file){s.speakerNotes.text=t+'\n\n界面来源：http://127.0.0.1:7862/，2026-10-18 当前运行的有声书工坊。\n截图原图：'+path.join(ASSETS,file)+'\n代码：'+path.join(ROOT,'audiobook_generator/ui/web_ui.py')+'\n截图使用已有本地书籍、剧本和音频，不代表本轮新生成或新验收。';}

// Replace the archival home image with the current UI, retaining the slide's composition.
const homeRec=before.records.find(r=>r.index===1);
const oldImage=homeRec.elements.find(e=>e.kind==='image');
if(!oldImage)throw Error('Source overview image not found');
p.delete([oldImage.id]);
await shot(original[1],'home_full.jpg',[65,25,680,390],{left:64,top:170,width:730,height:419},'当前有声书工坊首页，四步生成流程');
const oldFoot=homeRec.elements.find(e=>e.text?.includes('10 月 12 日'));
if(!oldFoot)throw Error('Archival footnote not found');
p.resolve(oldFoot.id).text='当前实际界面（2026-10-18）。后续各模块配有独立截图和操作说明';
note(original[1],'首页展示准备书籍、选择声音、多角色配音、确认生成四个入口步骤。已有书籍已载入，当前没有启动生成。','home_full.jpg');

const defs=[
 {after:4,title:'选章节：先用一章做小规模试验',file:'chapter_full.jpg',region:[90,365,630,310],frame:{left:64,top:190,width:750,height:369},
  blocks:[['书籍与章节','读取电子书目录，分别选择\n起始章和结束章。',186],['这次选了什么','《Flipped》第 5 章，\n共 14,311 个字符。',360]],
  foot:'对应统一流程中的“读取书籍、选择章节”。先试一章，便于检查人物配置和朗读效果',
  notes:'截图为已有 Flipped.source.epub 的章节选择。全书目录20项，本轮范围限定第5章Diving Under，显示14,311字符。这里展示范围选择和字符统计，不表示点击了生成。'},
 {after:7,title:'叙述者核对：这一章由谁来讲',file:'narration_full.jpg',region:[85,250,640,510],frame:{left:64,top:155,width:600,height:478},x:720,w:496,
  blocks:[['已有的分析结果','第 5 章由 Bryce 叙述，\n第 6 章由 Juli 叙述。\n每章可沿用对应人物的声音。',158],['界面里怎样调整','选章节，再指定叙述人物。\n确认后应用到本章叙述段，\n人物对白继续使用各自声音。',350]],
  foot:'当前第 5 章识别出 30 段叙述。多人轮流讲述的章节，需要逐段核对',
  notes:'载入已有 machine_proposal_final.json，含13角色、2章节、77段。章节5有62段、章节6有15段。界面显示“已确认当前副本”属于现有导入行为，不代表77段已经人工验收。分析来源标记仍为proposed。截图展示本章叙述声音的设置，没有点击应用或新生成。'},
 {after:12,title:'人物声音：给 Juli 选择一个固定声音',file:'role_full.jpg',region:[85,145,640,590],frame:{left:64,top:155,width:520,height:479},x:640,w:576,
  blocks:[['当前的设置','人物是 Juli Baker，朗读语言为英语，\n使用预设声音 Chloe，语速为 1.0。',158],['同一句话比较不同声音','右侧可输入试听文本，再试听当前人物。\n使用同样的句子，比较谁更容易听出差别。',322],['满意后保留参考录音','可固定一次满意的试听，供后续复用。\n描述声音也能采用这种方式减少变化。',486]],
  foot:'对应“给人物安排声音”。当前截图展示配置，本轮没有重新合成试听',
  notes:'同一份已载入的V2剧本，选择Juli Baker后实际显示Chloe、英语、1.0倍速。右侧试听结果为空，因此不能称这次试听成功。固定试听会保存本地参考音，之后试听或生成可能向MiMo发送参考音，此处未触发。'},
 {after:14,title:'检查开关：生成后先找出可疑片段',file:'checks_full.jpg',region:[85,435,640,315],frame:{left:64,top:185,width:750,height:369},
  blocks:[['检查与修复分别控制','上面的开关负责检查内容、\n人物声音和拼接处。',184],['当前没有开启自动重做','下面的自动修复开关关闭。\n先查看报告，再决定怎么改。',366]],
  foot:'对应“音频检查的完整过程”。找到本地模型不代表检查指标已经校准',
  notes:'真实界面中MiMo检查开启，自动修复关闭。已发现本地内容转写与声纹模型，但阈值及独立验收仍需按项目报告判断。读取既有报告不会调用付费合成。'},
 {after:20,title:'质量报告：哪里可疑，为什么要再听',file:'report_full.jpg',region:[97,410,615,510],frame:{left:64,top:155,width:570,height:473},x:690,w:526,
  blocks:[['逐段列出问题','每行记录章节、人物和片段位置。\n可以从列表定位到需要复核的录音。',156],['两个提示的含义','asr_mismatch：转写与应读文字有差异。\npitch_drift：音调变化较大，建议再听。',318],['未完成也单独保留','incomplete 表示还没有查清。\n音频可以已导出，但报告仍留有疑点。',480]],
  foot:'这里展示已有第 5 章报告。机器疑点需要核对，不能直接算作真实错误率',
  notes:'读取flipped_casting_preview_20261017目录既有quality.json，run833889352480474a859cd06200d0ed5e。报告显示第5章incomplete且音频已导出。本次运行累计1次合成请求（修复1次），历史已知101次且不全，两项可能重叠不相加。页面表格可水平滚动，此截图保留位置、维度、问题三列。原机器证据不被新的界面阅读替代。'},
 {after:21,title:'问题试听：直接听两句话的连接处',file:'context_full.jpg',region:[100,315,610,330],frame:{left:64,top:185,width:750,height:406},
  blocks:[['从编号找到对应录音','选择问题片段或拼接处后，\n下方加载相关的音频。',183],['实际例子 J076','同学的话接到下一段旁白。\n听两侧声音，判断停顿\n是否自然，再决定要不要改。',362]],
  foot:'可试听或下载问题上下文，也能下载完整报告，保留后续复核所需的依据',
  notes:'当前选择5:60:classmates:chunk:1与5:61:narrator:chunk:1之间的J076窗口，播放器显示约4秒。页面已加载既有J076.wav，此次未点击播放，也未做新的修复。项目历史J076曾确认停顿约2.04秒并调整至约1秒，具体历史结论见前文技术页，当前截图本身不重复证明验收结果。'},
 {after:29,title:'资源库：试听完成的章节并下载成果',file:'library_full.jpg',region:[85,250,640,570],frame:{left:64,top:155,width:530,height:472},x:650,w:566,
  blocks:[['按书籍或批次查看文件','左侧可筛选并选择文件。\n音频和对应文本都能保留下来。',156],['先听章节，再下载','右侧选择章节即可加载播放器，\n可调节播放速度，也能下载单个文件。',322],['需要一起带走时','切换到 ZIP 打包，将选中的文件\n整理为一个压缩包。',488]],
  foot:'截图使用已有《小王子》文件。播放器已加载约 3 分 32 秒音频，本轮未重新生成',
  notes:'资源库实际选中The_Little_Prince批次，包含0001_The_Little_Prince.mp3及同名txt，2文件约1.5MB。章节播放器已加载，时长3:32。当前为逐个下载模式，ZIP为已实现的可选下载模式，此轮未点击打包或清理文件。'}
];

const added=[];
for(const d of defs){
 const source=original[d.after-1];
 const s=source.duplicate();
 const state=await p.inspect({select:'$.slides[*]',include:['id','index','elements.id']});
 const rec=state.records.find(r=>r.id==='sl/'+s.id);
 p.delete(rec.elements.map(e=>e.id));
 s.moveTo(p.slides.items.indexOf(source)+1);
 s.background.fill=C.bg;
 text(s,d.title,64,48,1152,85,44,C.ink,true);
 await shot(s,d.file,d.region,d.frame,d.title+'，项目真实界面截图');
 for(const [h,b,y] of d.blocks) block(s,h,b,y,d.x??850,d.w??366);
 foot(s,d.foot);text(s,'00',1173,669,45,25,17,C.muted);
 note(s,d.notes,d.file);added.push(s.id);
}
if(p.slides.items.length!==37)throw Error('Unexpected slide count');
const state=await p.inspect({select:'$.slides[*]',include:['id','index','title','elements.id','elements.kind','elements.text','elements.position','notes.text']});
for(const rec of state.records){
 const f=rec.elements.find(e=>e.position?.left>1160 && e.position?.top>650 && /^\d{2}$/.test(e.text??''));
 if(!f)throw Error('Page marker missing '+rec.index);
 p.resolve(f.id).text=String(rec.index+1).padStart(2,'0');
}
const mapping=original.map((s,i)=>({original:i+1,final:p.slides.items.indexOf(s)+1,id:s.id}));
await fs.writeFile(path.join(BUILD,'mapping.json'),JSON.stringify({mapping,added:added.map(id=>({id,index:p.slides.items.findIndex(s=>s.id===id)+1})),screenshots:defs.map(d=>({file:d.file,slide:p.slides.items.findIndex(s=>s.id===added[defs.indexOf(d)])+1,crop:d.region}))},null,2));
await fs.writeFile(path.join(BUILD,'content.ndjson'),(await p.inspect({select:'$.slides[*]',include:['id','index','title','elements.text','elements.kind','notes.text']})).ndjson);
const tables=p.slides.items.flatMap((s,i)=>s.tables.items.length?[i+1]:[]);
const candidate=path.join(BUILD,'candidate.pptx');
await(await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:WORK,candidatePath:candidate,finalPath:FINAL,
 pythonExecutable:'/Users/yinzh/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'reference',families:[FONT],referencePath:SOURCE,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:path.join(BUILD,'validation.json')});
console.log('FINAL',result.finalPath);
const final=await PresentationFile.importPptx(await FileBlob.load(FINAL));
for(let i=0;i<final.slides.items.length;i++){
 const blob=await final.export({slide:final.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(BUILD,'final_renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
 console.log('RENDER',i+1);
}
