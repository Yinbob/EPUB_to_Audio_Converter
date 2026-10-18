import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {PresentationFile, FileBlob} from '@oai/artifact-tool';
import {finalizePresentation} from '/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations/container_tools/artifact_tool_utils.mjs';

const ROOT='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1';
const WORK=path.join(ROOT,'docs/presentation_20261018');
const BUILD=path.join(WORK,'build/audio_checks');
const SOURCE=path.join(WORK,'output/多角色有声书_项目进展与创新实现_通俗实例版_20261018.pptx');
const FINAL=path.join(WORK,'output/多角色有声书_音频检查技术详解_20261018.pptx');
const SKILL='/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations';
const FONT='PingFang SC';
const C={bg:'#F8FAFD',ink:'#16243B',muted:'#53627A',blue:'#245BDD',green:'#176C5C',line:'#CED8E8',pale:'#EAF0FC',white:'#FFFFFF'};
await fs.mkdir(path.join(BUILD,'final_renders'),{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const before=await p.inspect({select:'$.slides[*]',include:['id','index','layout','title','elements.id','elements.kind','elements.text','elements.position']});
await fs.writeFile(path.join(BUILD,'before.ndjson'),before.ndjson);
await fs.writeFile(path.join(BUILD,'before-14.png'),new Uint8Array(await (await p.slides.items[13].export({format:'png',scale:1})).arrayBuffer()));
await fs.writeFile(path.join(BUILD,'before-14.layout.json'),await (await p.slides.items[13].export({format:'layout'})).text());
const sourceSlideIds=p.slides.items.map(s=>s.id);
const selected=before.records.find(r=>r.index===13);
const first=p.resolve(selected.id);
p.delete(selected.elements.map(e=>e.id));
const additions=[];
for(let i=0;i<6;i++){
 const s=first.duplicate();
 s.moveTo(14+i);
 additions.push(s);
}
if(p.slides.items.length!==30 || p.slides.items[13].id!==first.id || additions.some((s,i)=>p.slides.items[i+14].id!==s.id)) throw Error('Unexpected slide insertion order');

function text(s,t,x,y,w,h,size=27,color=C.ink,bold=false){
 const z=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 z.text=t;z.text.insets=0;z.text.style={fontSize:size,typeface:FONT,color,bold};return z;
}
function page(n,title){
 const s=p.slides.items[n-1];s.background.fill=C.bg;
 text(s,title,64,48,1150,85,44,C.ink,true);
 text(s,String(n).padStart(2,'0'),1173,669,45,25,17,C.muted);
 return s;
}
function foot(s,t){text(s,t,64,636,1090,42,18,C.muted);}
function heading(s,h,b,y,{size=27,w=1110}={}){
 text(s,h,64,y,w,42,30,C.blue,true);
 text(s,b,64,y+48,w,112,size,C.muted);
}
function node(s,t,x,y,w=270,h=92,color=C.blue,size=25){
 const z=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:C.white,line:{fill:color,width:2}});
 z.text=t;z.text.insets=8;z.text.style={fontSize:size,typeface:FONT,color:C.ink,bold:true,alignment:'center',verticalAlignment:'middle'};return z;
}
function link(s,a,b){s.shapes.connect(a,b,{kind:'straight',fromSide:'right',toSide:'left',line:{fill:C.blue,width:2.5},tail:{type:'triangle',width:'med',length:'med'}});}
function table(s,values,{x=64,y=185,w=1152,h=350,widths,size=25}={}){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,...(widths?{columnWidths:widths}:{})});
 for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){
  const a=t.getCell(r,c);a.fill=r===0?C.pale:r%2?C.white:'#F1F5FA';a.text.style={fontSize:size,typeface:FONT,color:r===0?C.blue:C.ink,bold:r===0};
 }
 t.borders.assign({fill:C.line,width:1,style:'solid'});return t;
}
function notes(s,body,sources){s.speakerNotes.text=body+'\n\n项目源码与本地证据（截至 2026-10-18）：\n'+sources.map(v=>path.join(ROOT,v)).join('\n');}

// 14: preserve the overview's place, and distinguish the independent checks.
let s=page(14,'音频检查的完整过程');
text(s,'输入：每段的实际朗读文本、人物编号、音频，以及该人物的参考录音',64,163,1152,78,29,C.blue,true);
let a=node(s,'读取录音\n先检查信号',64,285,240,100);
let b=node(s,'检查这一段\n内容、声音和语速',368,285,240,100);
let c=node(s,'检查相邻两段\n连接处和完整内容',672,285,240,100);
let d=node(s,'保存检查单\n带上下文试听',976,285,240,100,C.green);link(s,a,b);link(s,b,c);link(s,c,d);
heading(s,'每一项留下自己的判断依据','例如：多出了哪个词、声音差了多少、哪两段之间停得太久。\n内容没有差异，也仍要检查人物声音和连接处。',440,{size:28});
foot(s,'“正确”分成多个维度，机器筛查和人工试听分别留记录，未查清的项目继续保留');
notes(s,'QualityEvaluator.evaluate_chunk 分别产生 signal、content、consistency 维度。evaluate_boundary 对每组相邻片段产生 stitching、content 维度。正式管线先检查各块，再为相邻两块组装完整窗口并转写检查。三类输入以 ReadingChunk.tts_text、role_id、音频路径和角色 anchor 为准，不拿未经处理的书籍排版文本直接比对。不得把文本一致、能解码、人物一致或主观自然度合并成一个未经验证的“正确率”。',[
 'audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/pipeline.py','audiobook_generator/audio_core/models.py']);

// 15: exact content-checking inputs, local model, and comparison normalization.
s=page(15,'内容检查：录音怎样变成可比较的文字');
a=node(s,'录音文件\n本地 SenseVoice 识别',64,171,300,96);
b=node(s,'原文与转写各做整理\n统一写法，再分字或分词',490,171,300,96);
c=node(s,'逐项比较\n保存差异和原始录音',916,171,300,96,C.green);link(s,a,b);link(s,b,c);
table(s,[['具体处理','程序如何实现','为什么需要这一步'],
 ['转成文字','SenseVoiceSmall 在 CPU 上运行，\n自动识别语言，取出纯文本','模型目录由本地配置指定，\n缺模型或转写为空就保留未查清'],
 ['整理比较文本','统一全角、半角、大小写和引号，\n处理支持的数字、日期与显式词典','20 books 与 twenty books\n可以按同样内容比较'],
 ['确定比较单位','中文按字，英文按词，\n保留英文词界和缩写内部撇号','避免把 don’t 的否定含义、\n人名或编号随意抹掉']],
 {y:315,h:276,widths:[185,530,437],size:23});
foot(s,'比较基准是实际发送给语音服务的 tts_text，书籍原文、朗读改写和比较结果分别保存');
notes(s,'转写路径：QualityEvaluator.transcript → SenseVoiceBackend.__call__ → voxcpm_asr.transcribe_audio。FunASR AutoModel.generate(input=..., language="auto", use_itn=True)，从 result[0]["text"].split("|>")[-1] 获取正文。核心后端要求已配置的本地模型目录，固定 CPU，模型版本纳入缓存指纹，不隐式下载。comparison_details 先做 Unicode NFKC、弯撇号转直撇号、normalize_reading_text、显式词典与内置数值等价，再按语言分词。英文 comparison_reading 仅支持有边界的数值/日期等价，模糊编号和缩略词不任意展开。中文按规范化后的字符比较，混合语言使用 mixed_token 并单独记录指标。',[
 'audiobook_generator/audio_core/backends.py','audiobook_generator/utils/voxcpm_asr.py','audiobook_generator/audio_core/reading.py','audiobook_generator/audio_core/english_reading.py','audiobook_generator/audio_core/quality.py']);

// 16: edit-distance details, numerical example, and ASR false positive.
s=page(16,'内容检查：怎样找出多读、漏读和错读');
text(s,'程序寻找“最少需要改几处”，把两份文本对齐',64,162,1150,44,30,C.blue,true);
text(s,'增加、删除、替换各记 1 次，相同内容记 0 次。这种方法叫编辑距离。',64,212,1152,46,27,C.muted);
text(s,'D(i,j) = min{ D(i−1,j)+1, D(i,j−1)+1, D(i−1,j−1)+[a[i]≠b[j]] }',64,265,1152,44,27,C.ink,true);
text(s,'D(i,j) 表示原文前 i 个字词与转写前 j 个字词的最少改动数',64,311,1152,38,23,C.muted);
table(s,[['示意输入','逐字比较的结果'],['应该读的内容，共 6 字','我　今　天　去　学　校'],['识别出的内容，共 8 字','我　今　天　今　天　去　学　校'],['找到的差异','多出“今天”两字，差异率 = 2 ÷ 6 ≈ 33.3%']],{y:358,h:192,widths:[370,782],size:25});
text(s,'差异率 =（替换数 + 漏读数 + 多读数）÷ 原文单位数',64,574,1152,42,26,C.blue,true);
foot(s,'真实 R034 曾被识别为“Comome on”，人工听整句后确认是识别误报，原机器证据仍保留');
notes(s,'align_text 使用 Levenshtein 动态规划。D(i,j) 表示参考前 i 个单位与识别前 j 个单位的最小改动数。边界 D(i,0)=i，D(0,j)=j。先填表，再从右下角回溯得到 replace/delete/insert，保存 reference_index、hypothesis_index 和具体文本。中文指标 CER，英文 WER，混合文本 mixed_token_error_rate。error_rate=dist/max(1,len(reference_tokens))，多读很多时可以超过 100%，不能把 1-error_rate 直接称为音频正确率。索引定位到规范化后的字词，不等于毫秒级声学时间戳。只要出现任意差异，content 仍为 incomplete 并写 asr_mismatch，不是凭一个百分比阈值确认缺陷。本页中文例子为算法示意，不是项目实测音频。R034 的真实接受与误报裁决见 v49：要求精确 verified_tts_text、整块内容完整、无增读及音频/报告/告警指纹绑定，不能用一小段试听消除整块提示。',[
 'audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/quality_review.py','docs/validation/audio_core_20261017/README.md','docs/validation/audio_core_20261017/asr_adjudication_actual_v49.json']);

// 17: ECAPA comparison with explicit guardrails and uncalibrated threshold.
s=page(17,'人物声音检查：与同一份参考录音比较');
a=node(s,'当前录音和人物参考音\n分别提取声音特点',64,165,300,96);
b=node(s,'ECAPA 模型\n各得到一组数字',490,165,300,96);
c=node(s,'比较两组数字\n越不相似，距离越大',916,165,300,96);link(s,a,b);link(s,b,c);
table(s,[['技术细节','当前实现'],
 ['输入条件','转成单声道、16 kHz，每段至少 3 秒有效语音。太短就暂不判断'],
 ['比较算法','向量先归一化，再算距离 d = 1 − cos(u,v)，也就是 1 − u·v'],
 ['提示条件','d > 0.35 时标记“疑似换声”。这个阈值尚未用独立数据校准'],
 ['参考录音来源','使用固定参考音，或用内容与信号检查通过的首个合适片段建立参考']],
 {y:311,h:275,widths:[210,942],size:24});
foot(s,'例如 Bryce 始终对照同一份参考音。距离低也不会自动证明人物身份一致，还要试听');
notes(s,'SpeakerEncoder 使用本地 SpeechBrain ECAPA EncoderClassifier，模型权重齐全才允许运行，CPU 推理。mono_resampled 将声道取均值并用 scipy.signal.resample_poly 抗混叠重采样到 16 kHz。有效语音近似为 RMS≥0.003 的 20 ms 帧，min(总时长,有效帧时长)须≥3 s。模型输出扁平向量并 L2 归一化，QualityEvaluator.embedding 再验证有限数值、非空且范数>0。distance=1−dot(e_current,e_anchor)，>0.35 只触发 speaker_drift，speaker_threshold_kind=uncalibrated。consistency 不会因距离小而自动 passed。参考音优先采用有效固定配置，自动 bootstrap 参考只适用于非 design/clone、无问题且内容通过的片段；这是程序可用参考，不等于人已确认身份。比较时校验参考音 SHA256 与记录绑定，文件发生变化即拒绝沿用依据。',[
 'audiobook_generator/audio_core/backends.py','audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/audio.py','audiobook_generator/audio_core/pipeline.py','docs/validation/audio_core_20261017/README.md']);

// 18: actual signal-based rate/pitch estimates and when to suppress them.
s=page(18,'声音变化检查：语速和音调怎样计算');
heading(s,'语速：用字词数除以实际发声时间','每 20 毫秒算一次声音强度，找出在发声的部分。也可启用 Silero 找人声。\n语速 = 规范化后的字词数 ÷ 发声秒数，英文再乘 60 得到每分钟词数。',161,{size:26});
text(s,'当前提示线：中文超过 4.3 字/秒，英文超过 300 词/分。\n与参考音比较时，快慢倍数超过 1.3，也会提示复核。',64,302,1152,79,26,C.ink,true);
heading(s,'音调：估计每个短窗口的基频，再取中间值','录音转为 8 kHz，以 40 毫秒窗口、20 毫秒步长做自相关，估计声音周期。\n变化量 = 12 × log₂（当前基频 ÷ 参考基频），单位是半音。',405,{size:26});
text(s,'相差超过 6 个半音，且两段各有至少 50 个有效音调窗口，才提示变化。',64,550,1152,72,26,C.ink,true);
foot(s,'这些都是筛查线。内容多读或漏读时，停止用参考字词数判断语速，情绪变化也要人工区分');
notes(s,'signal_features 的 frame_rms 默认帧宽20 ms，RMS≥0.003 估计有效发声，active=min(duration,active_seconds)。可选 SileroVAD 使用随包 ONNX 模型、16 kHz 输入与 get_speech_timestamps，默认 enable_vad=False，失败则沿用轻量估计。reading_count 用规范化参考计数，并非实测逐词时间戳。count≥5、总时长≥1 s、语言为en/zh且没有已发现的内容差异才使用语速规则。英文阈值 max_english_wpm/60，默认300词/分；中文max_rate默认4.3字/秒。abs(log(rate/reference_rate))>log(1.3)，等价于ratio>1.3或ratio<1/1.3，绝非对称±30%。当前或参考文本对齐异常、单位不同时不做相对语速判断。pitch_summary 将音频重采样到8 kHz，320点窗口、160点步长，去均值并加Hann窗，对RMS≥0.01的帧自相关，候选lag16..133且归一化峰相关≥0.55才纳入。取中位基频和四分位距。shift=12log2(f_current/f_reference)，|shift|>6且双方 voiced_frames≥50才触发pitch_drift。这是轻量估计和未校准启发式提示，不是训练过的情绪或错误发音分类器。',[
 'audiobook_generator/audio_core/audio.py','audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/backends.py','audiobook_generator/audio_core/models.py']);

// 19: distinguish short acoustic windows from complete content windows.
s=page(19,'连接处检查：句尾和下一句怎样接起来');
text(s,'声音特征看左段末尾 2 秒、右段开头 2 秒，内容核对使用完整两段',64,162,1152,76,28,C.blue,true);
table(s,[['检查项','计算方法','当前怎样使用'],
 ['是否突然“啪”一下','比较接点样本值，\n有补入停顿时也检查两侧是否突变','跳变幅度 > 0.15，\n提示疑似爆音'],
 ['音量、音色突变','比较两侧 20 毫秒的强度，\n再比较 512 点频谱的差别','记录分贝差和频谱距离，\n供复核或可选模型使用'],
 ['是否停得太久','以 20 毫秒低能量帧，\n统计左尾和右头的无声时长','两侧无声之和超过\nmax(1.5秒,计划停顿+0.8秒)就提示'],
 ['内容是否完整','把完整左句和右句拼起来再转写，\n与完整两句文字比较','有差异就保留内容疑点，\n不拿短窗口去对齐整句']],
 {y:255,h:325,widths:[215,485,452],size:23});
text(s,'实际 J076：约 2.04 秒停顿经试听确认后，才移除多余静音，调整为约 1 秒。',64,594,1152,42,25,C.blue,true);
foot(s,'默认先用规则筛查。可选连接处分类模型仍缺独立真实缺陷验收，不能替代人工确认');
notes(s,'boundary_features 默认 window_seconds=2.0。左右短窗口先单声道16 kHz，边缘20 ms即320点算RMS，rms_jump_db=|20log10(RMS_left/RMS_right)|。边缘各512点FFT幅度谱作L2归一化，计算欧氏距离。tail/head由完整片段的连续边缘20 ms低能量帧（RMS<0.003）计数，保守估计静音。added_pause=planned−tail−head，若>0，sample_jump=max(|left_last|,|right_first|)，否则=|left_last−right_first|。九个特征包括样本跳变、RMS分贝差、谱距离、左右发声标记、左右静音、计划停顿、是否同角色。默认 heuristic_labels 只产生疑似click和过长gap，两条规则如页面所列，并不直接确认cutoff或overlap。可选 boundary-logistic-v1 将9项标准化，四个独立sigmoid头预测click/cutoff/overlap/gap，训练集拟合、独立dev选阈值（先限制dev误报≤5%再最大化召回），同源变体不得跨split。真实独立评估未完成，因此即使预测完成，stitching维度也保持incomplete。完整两句ASR输入是assembled_window，与两个完整tts_text拼接比较，不是只拿各2秒。J076真实v46移除已确认静音中央1.04秒，停顿2.04→1.00秒，原语音保留，v47用户确认三处修复正常。',[
 'audiobook_generator/audio_core/audio.py','audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/boundary_model.py','docs/validation/audio_core_20261017/README.md']);

// 20: signal checks, exact status semantics, and version-safe evidence.
s=page(20,'信号检查与最终判断');
table(s,[['直接能计算的指标','当前检查条件','得到什么结果'],
 ['空音频','采样点数量等于 0','记录已确认的严重错误'],
 ['音量过小','归一化样本峰值 < 0.003','记录已确认的信号错误'],
 ['幅度顶到上限','|样本值| ≥ 0.999 的占比 > 0.2%','提示削波，记录信号错误']],
 {y:170,h:260,widths:[260,495,397],size:25});
a=node(s,'通过\n该维度检查已完成',64,485,330,82,C.green,25);
b=node(s,'未查清\n有疑点或检查未完成',475,485,330,82,C.blue,25);
c=node(s,'失败\n已确认严重错误',886,485,330,82,C.blue,25);
text(s,'报告记录音频 SHA256、模型版本和具体差异，音频一变就不能沿用旧结论。',64,592,1152,40,25,C.ink,true);
foot(s,'“信号通过”只代表这些指标正常。整体还有疑点或未完成维度时，就继续保留未查清');
notes(s,'signal_features 解码为float32 always_2d，样本需有限且采样率有效。peak=max(abs(samples))，clipped_fraction=mean(abs(samples)>=0.999)，阈值>0.002。evaluate_chunk 对 samples==0、peak<0.003、clipped_fraction>0.002 分别生成 empty_audio/too_quiet/clipping，certainty=confirmed、severity=error、signal=failed。这里的“确认”是程序对信号阈值事实的确认，不能外推为人工自然度结论。QualityReport.status 精确逻辑：存在confirmed error则failed；否则有任意issues或任意dimension=incomplete则incomplete；否则passed。speaker未校准或缺模型、stitching未验收时不会因为没越阈值而自动passed。SHA256绑定音频，ASR缓存键同时含音频SHA、模型fingerprint和处理版本；检查前后校验文件和模型未变，避免拿旧缓存或旧人工结论套到新版本。人审结论需精确绑定报告、音频、告警及所听上下文，机器原始依据保留。',[
 'audiobook_generator/audio_core/audio.py','audiobook_generator/audio_core/quality.py','audiobook_generator/audio_core/models.py','audiobook_generator/audio_core/quality_review.py']);

// The remaining original slides keep their native objects, notes, and layouts.
const inspectAfter=await p.inspect({select:'$.slides[*]',include:['id','index','layout','title','elements.id','elements.kind','elements.text','elements.position']});
for(const rec of inspectAfter.records.filter(r=>r.index>=20)){
 const expectedOldNumber=String(rec.index-5).padStart(2,'0');
 const footer=rec.elements.find(e=>e.text===expectedOldNumber && e.position?.left>1160 && e.position?.top>650);
 if(!footer)throw Error('Cannot locate original slide footer '+rec.index);
 p.resolve(footer.id).text=String(rec.index+1).padStart(2,'0');
}
for(let i=0;i<13;i++)if(p.slides.items[i].id!==sourceSlideIds[i])throw Error('Unintended initial slide reorder');
for(let i=14;i<24;i++)if(p.slides.items[i+6].id!==sourceSlideIds[i])throw Error('Unintended remaining slide reorder');
const after=await p.inspect({select:'$.slides[*]',include:['id','index','title','layout','elements.text','elements.kind','notes.text']});
await fs.writeFile(path.join(BUILD,'content.ndjson'),after.ndjson);
const tables=p.slides.items.flatMap((s,i)=>s.tables.items.length?[i+1]:[]);
const candidate=path.join(BUILD,'candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
const result=await finalizePresentation({workspaceDir:WORK,candidatePath:candidate,finalPath:FINAL,
 pythonExecutable:'/Users/yinzh/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'reference',families:[FONT],referencePath:SOURCE,referenceSha256:crypto.createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex')},
 verifyArtifactToolImport:true,receiptPath:path.join(BUILD,'validation_v2.json')});
console.log('FINAL',result.finalPath,'slides',p.slides.items.length);
const final=await PresentationFile.importPptx(await FileBlob.load(FINAL));
for(let i=0;i<final.slides.items.length;i++){
 const png=await final.export({slide:final.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(BUILD,'final_renders',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
 console.log('RENDER',i+1);
}
