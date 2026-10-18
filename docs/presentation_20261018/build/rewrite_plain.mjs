import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {PresentationFile,FileBlob} from '@oai/artifact-tool';
import {finalizePresentation} from '/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations/container_tools/artifact_tool_utils.mjs';

const ROOT='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1';
const WORK=path.join(ROOT,'docs/presentation_20261018');
const BUILD=path.join(WORK,'build/plain_revision');
const SKILL='/Users/yinzh/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations';
const SOURCE=path.join(WORK,'output/多角色有声书_项目进展与创新实现_技术原理详解版_20261018.pptx');
const FINAL=path.join(WORK,'output/多角色有声书_项目进展与创新实现_通俗实例版_20261018.pptx');
const FONT='PingFang SC';
const C={bg:'#F8FAFD',ink:'#16243B',muted:'#53627A',blue:'#245BDD',green:'#176C5C',line:'#CED8E8',pale:'#EAF0FC',white:'#FFFFFF',dark:'#15233A'};
await fs.mkdir(path.join(BUILD,'final_renders'),{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const before=await p.inspect({select:'$.slides[*]',include:['id','index','layout','elements.id','elements.kind','elements.text']});
await fs.writeFile(path.join(BUILD,'before.ndjson'),before.ndjson);
for(const rec of before.records){
 const remove=rec.elements.filter(e=>!(rec.index===1&&e.kind==='image')).map(e=>e.id);
 p.delete(remove);
}
function text(s,t,x,y,w,h,size=27,color=C.ink,bold=false){
 const z=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 z.text=t;z.text.insets=0;z.text.style={fontSize:size,typeface:FONT,color,bold};return z;
}
function page(n,title,dark=false){
 const s=p.slides.items[n-1];s.background.fill=dark?C.dark:C.bg;
 text(s,title,64,48,1150,85,44,dark?C.white:C.ink,true);
 text(s,String(n).padStart(2,'0'),1173,669,45,25,17,dark?'#C4D5F7':C.muted);
 s.speakerNotes.text+='\n本页改用日常表达。已有技术细节与本地来源保留在备注中。';
 return s;
}
function foot(s,t){text(s,t,64,636,1090,42,18,C.muted);}
function hb(s,h,b,x=64,y=180,w=1110,size=27){
 text(s,h,x,y,w,43,30,C.blue,true);text(s,b,x,y+49,w,100,size,C.muted);
}
function node(s,t,x,y,w=270,h=92,color=C.blue,size=25){
 const z=s.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill:C.white,line:{fill:color,width:2}});
 z.text=t;z.text.insets=8;z.text.style={fontSize:size,typeface:FONT,color:C.ink,bold:true,alignment:'center',verticalAlignment:'middle'};return z;
}
function link(s,a,b,from='right',to='left'){
 s.shapes.connect(a,b,{kind:from==='right'&&to==='left'?'straight':'elbow',fromSide:from,toSide:to,line:{fill:C.blue,width:2.5},tail:{type:'triangle',width:'med',length:'med'}});
}
function table(s,values,{x=64,y=185,w=1152,h=350,widths,size=25}={}){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,...(widths?{columnWidths:widths}:{})});
 for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){
  const a=t.getCell(r,c);a.fill=r===0?C.pale:r%2?C.white:'#F1F5FA';a.text.style={fontSize:size,typeface:FONT,color:r===0?C.blue:C.ink,bold:r===0};
 }
 t.borders.assign({fill:C.line,width:1,style:'solid'});return t;
}

// 01
let s=page(1,'把电子书变成多角色有声书',true);
text(s,'我们做了什么，怎样做成',64,205,1110,105,60,C.white,true);
text(s,'给不同人物安排声音\n找出读错的地方，尽量只修有问题的部分',68,365,1100,128,32,'#D2DFF7');
text(s,'项目进展与改进思路    2026 年 10 月 18 日',68,569,1100,42,24,'#C4D5F7');

// 02 保留原界面截图及其原始位置
s=page(2,'这个项目能帮我们做什么');
hb(s,'把书读成有声书','上传电子书、选择章节，\n让旁白和不同人物分别朗读。',835,184,380,25);
hb(s,'读错一小段，就修这一段','找到多读、漏读或停顿过长\n的位置，尽量少重做整章。',835,390,380,25);
foot(s,'左图是 10 月 12 日的实际界面，后续新增功能用流程图说明');

// 03
s=page(3,'目前已经做成了哪些功能');
table(s,[['制作步骤','已经能做什么','目前的情况'],['读入书籍','提取章节，整理人物和人物别名','支持中英文，允许人工修改'],['安排声音','选现成声音、用文字描述、模仿参考音','已选好的声音可以锁定'],['生成音频','逐段生成，保存结果，按顺序拼起来','新的整套流程目前接入 MiMo'],['检查与修正','找读错、长停顿、换声等疑点','已完成部分实际问题的修正'],['网页操作','选章节、确认配置、查看和下载结果','后台流程已做测试']],{y:175,h:400,widths:[180,570,402],size:25});
foot(s,'原来的转换器仍支持多种语音服务，本轮重点做好 MiMo 的整套制作流程');

// 04 细化为十二步，三行蛇形连接
s=page(4,'从上传书籍到下载音频，具体怎么走');
const steps=[
 ['1 上传书籍','选择要朗读的章节'],['2 找出说话的人','谁在讲故事或说话'],
 ['3 对照书中原文','核对是否漏字、改字'],['4 选声音并确认','试听声音，设置语速'],
 ['5 整理实际读法','处理数字、缩写读法'],['6 按句分成小段','记录人物和停顿'],
 ['7 逐段生成并保存','MiMo 生成，可复用'],['8 找出可疑问题','查漏读、重复和停顿'],
 ['9 只修有问题的段','剪多余内容或重读'],['10 再查前后两句','更好才保留新版'],
 ['11 拼成整章音频','检查整章能否播放'],['12 试听确认并下载','保留问题单和原音']
];
const ns=[];
for(let i=0;i<steps.length;i++){
 const row=Math.floor(i/4),col=row%2?3-i%4:i%4,x=64+col*304,y=174+row*147;
 const n=node(s,steps[i].join('\n'),x,y,240,104,C.blue,22);ns.push(n);
}
for(let i=0;i<ns.length-1;i++){
 const row=Math.floor(i/4);
 if(i%4===3)link(s,ns[i],ns[i+1],'bottom','top');
 else if(row%2)link(s,ns[i],ns[i+1],'left','right');
 else link(s,ns[i],ns[i+1]);
}
foot(s,'修复有次数和用时限制，拿不准的问题留给人工试听，不会当作已经通过');

// 05 简单概括，创新编号与后文一致
s=page(5,'三个创新方向，分别解决什么问题');
table(s,[['改进方向','项目中遇到的具体问题','我们的做法'],
 ['谁讲故事，\n就用谁的声音','《Flipped》人物用“我”讲故事，\n部分文字曾被分给普通旁白','按本章原文找出讲述者，\n让自述与本人对白共用声音'],
 ['经常对话的人，\n声音尽量不同','试用的合格英语声音只有两个，\n给旁白留一个后，角色声音不够','常对话的人优先用不同声音，\n不够时用固定描述补充'],
 ['哪里读错，\n就优先修哪里','R039 读完又重复，\nJ076 两句话之间停得太久','只处理问题段，\n再检查前后句有没有受影响']],
 {y:180,h:354,widths:[270,458,424],size:24});
text(s,'共同目标：少弄错说话的人，少重复生成，少让人反复试听',64,561,1150,56,29,C.blue,true);
foot(s,'已有文字归属修正和音频修复案例，声音分配是否更好认仍需听众比较');

// 06
s=page(6,'创新一：谁讲故事，就用谁的声音');
hb(s,'具体问题','《Flipped》的两章分别由 Bryce 和 Juli 用“我”讲述。\n早期拆分时，有些人物自述被当成了普通旁白。',64,170,1120,28);
let a=node(s,'Bryce 讲故事\n沿用 Bryce 的声音',64,360,330,100,C.green);
let b=node(s,'Juli 讲故事\n沿用 Juli 的声音',480,360,330,100,C.green);
text(s,'换一章，\n重新判断是谁在讲',890,377,310,90,28,C.blue,true);
text(s,'已完成：两章的文字分配已修正，自述和本人对白共用声音配置。',64,525,1140,68,29,C.ink,true);
foot(s,'这次检查确认的是文字和声音的分配，没有为这两章重新生成语音');

// 07
s=page(7,'怎么做到：每一句都能回到书中核对');
a=node(s,'模型先判断\n这句是谁在说',64,194,290,96);
b=node(s,'程序对照原文\n检查有没有漏字或改字',495,194,290,96);
let c=node(s,'找到人物后\n使用已保存的声音',926,194,290,96);link(s,a,b);link(s,b,c);
hb(s,'每一段都记住它在原书中的位置','把所有小段拼回去，要能对应完整章节。\n判断讲述者时，还要留下书里的原句，让人能检查理由。',64,359,1110,28);
text(s,'找不到可靠依据时，先用普通旁白，并标出“需要复核”。',64,538,1140,55,30,C.blue,true);
foot(s,'程序可以检查有没有漏字，但“到底是谁在说”仍可能需要人来确认');

// 08
s=page(8,'书上怎么写，实际怎么读');
table(s,[['书上写的内容','可以怎样处理','为什么这样做'],['增长 3.5%','读成“增长百分之三点五”','让朗读更自然，保留原文不动'],['20 books / twenty books','检查时允许这两种写法对应','避免把数字写法差异当成读错'],['C’mon','本次修复改用 Come on! 朗读','解决 R034 一个词开头反复读的问题'],['人名、编号、多音字','拿不准就保留，交给人试听','避免程序擅自改出新错误']],{y:182,h:347,widths:[300,470,382],size:25});
text(s,'书籍原文和“发给语音服务的读法”分开保存，修改有记录。',64,563,1145,56,29,C.blue,true);
foot(s,'录音转成的文字相同，也不能证明多音字读对了，最终还要听声音');

// 09
s=page(9,'创新二：经常对话的人，声音尽量不同');
hb(s,'具体问题','试用的英语声音库里，经过试听确认的现成声音只有 Mia 和 Chloe。\n旁白占用一个后，就很难给其他人物各分一种声音。',64,170,1120,27);
a=node(s,'对白多的角色\n优先选现成声音',64,365,320,102);
b=node(s,'其他角色\n用固定文字描述声音',480,365,320,102);
c=node(s,'经常互相说话的人\n优先拉开声音差别',896,365,320,102,C.green);link(s,a,b);link(s,b,c);
text(s,'实际试用：用文字设定两个角色的声音，六条录音经试听确认容易区分。',64,529,1140,70,28,C.ink,true);
foot(s,'这里只确认了这两个角色的录音，还不能说自动分配一定比随机分配更好');

// 10
s=page(10,'怎么做到：先让不同声音读同样的句子');
a=node(s,'准备相同的试听句\n每种声音至少读两句',64,187,290,96);
b=node(s,'先听内容是否完整\n再记录声音特点',495,187,290,96);
c=node(s,'比较不同声音\n是否容易听成同一个人',926,187,290,96);link(s,a,b);link(s,b,c);
hb(s,'为什么要读相同的句子','如果一个声音读问句，另一个读感叹句，差别可能来自语气。\n让它们读同样的内容，比较才更公平。',64,347,1110,28);
hb(s,'电脑怎么参与比较','程序把声音特点记成一组数字，比较它们有多相似。\n换几句话再比，避免只凭一句话就认定两种声音不同。',64,493,1110,27);
foot(s,'电脑给出的相似程度只是参考，最终要请听众判断能不能认出人物');

// 11
s=page(11,'怎么做到：把声音优先分给最需要区分的人');
hb(s,'先看哪些人物经常一来一回地说话','程序按原文统计两个人轮流说话的次数。\n对话越频繁，越优先给他们安排差别较大的声音。',64,173,1110,28);
hb(s,'同时保留用户的选择','已经锁定的声音不会被自动改掉。\n也可以要求旁白单独用一种声音，或不同人物不共用声音。',64,327,1110,28);
hb(s,'方案少就逐个比较，方案多就先做好主要人物','先给经常说话的人分配，再尝试交换声音，看看能不能更容易区分。\n还会考虑声音是否适合人物，尽量少改已经定好的安排。',64,481,1110,26);
foot(s,'这是当前程序的分配方法，是否真的更好听、更好认，需要专门做试听比较');

// 12
s=page(12,'现在可以怎样给人物安排声音');
table(s,[['方法','用户要做什么','项目中的具体例子'],['选现成声音','直接选择服务里已有的声音','Juli 曾使用 Chloe'],['用文字描述声音','写清年龄感、音色和说话方式','同学群体使用固定的声音描述'],['模仿一段参考录音','提供参考音，让服务照着声音来读','Bryce 先试读几句，再用于整章']],{y:186,h:310,widths:[240,450,462],size:26});
a=node(s,'每个人物保存一份\n声音设置',88,545,300,65);
b=node(s,'换章时继续使用\n同一份设置',490,545,300,65);
c=node(s,'声音换过之后\n重新试听确认',892,545,300,65);link(s,a,b);link(s,b,c);
foot(s,'模仿参考音通常称为“声音克隆”，换过声音后的录音不能沿用旧试听结论');

// 13
s=page(13,'生成之后，重点检查哪几类问题');
table(s,[['要检查什么','程序怎样找疑点','人还需要注意什么'],['有没有读错','把录音转成文字，再与原文比较','文字可能识别错，不能直接删声音'],['两段连得顺不顺','查看句尾句首、音量和停顿','爆音、卡顿和长停顿需要试听'],['人物声音变没变','与该人物已确认的录音比较','情绪变化也会让声音听起来不同'],['文件是否正常','检查过响、长时间无声及能否播放','文件能播放，不等于每句话都合格']],{y:183,h:370,widths:[240,500,412],size:25});
foot(s,'每项分别标记“通过”“有问题”或“还没查清”，没查清不会自动算通过');

// 14
s=page(14,'怎么找到疑点：让电脑先帮我们听一遍');
hb(s,'第一步，把录音变成文字','一字一词地与要读的内容比较，标出多读、漏读和读成别的词的位置。\n英文按词比较，中文按字比较。',64,171,1110,27);
hb(s,'第二步，与这个人物之前的声音比较','看看声音、音调和速度有没有明显变化。\n句子太短或情绪变化太大时，先提示复核，不急着判断读错。',64,328,1110,27);
a=node(s,'前一句的结尾',64,516,270,76);
b=node(s,'两句话连起来\n检查停顿和声音突变',480,516,320,76);
c=node(s,'后一句的开头',946,516,270,76);link(s,a,b);link(s,b,c);
foot(s,'程序负责缩小试听范围，拿不准的地方保留录音和提示，让人最后决定');

// 15
s=page(15,'创新三：哪里读错，就优先修哪里');
table(s,[['首章中的实际问题','这次怎样修','解决了什么'],['R039 正文读完后又重复','留下完整正文，去掉后面的重复','不用把整章再生成一遍'],['J076 两句之间停得太久','去掉已确认的多余无声部分','让连接处恢复到约 1 秒停顿'],['R034 一个词开头读了几遍','改用 Come on! 的读法重新生成','只增加一次生成请求']],{y:185,h:310,widths:[350,465,337],size:25});
text(s,'这几处都已做局部试听确认，原始录音仍然保留。',64,543,1140,60,30,C.blue,true);
foot(s,'修复一个地方之后，还要听前后两句，防止修好这里、影响旁边');

// 16
s=page(16,'怎么控制重试：给制作过程设一个上限');
text(s,'事先设好：最多请求几次、修几次、补读多少字、用多长时间',64,173,1150,64,30,C.blue,true);
a=node(s,'确实需要重新读\n只发送问题段',64,285,290,96);
b=node(s,'先检查剩余额度\n登记这次尝试',495,285,290,96);
c=node(s,'请求语音服务\n记录成功或失败',926,285,290,96);link(s,a,b);link(s,b,c);
hb(s,'失败的一次也记下来','避免网络或生成失败后反复重试，把次数悄悄用完。\n上限到了就停止追加，把仍未解决的问题列出来。',64,440,1110,28);
foot(s,'目前按次数、文字量和时间控制，尚未直接计算花了多少元');

// 17
s=page(17,'怎么判断修好了：新旧版本一起比较');
a=node(s,'前一句',64,176,235,80);
b=node(s,'修改后的这一句',424,176,300,80,C.green);
c=node(s,'后一句',849,176,235,80);link(s,a,b);link(s,b,c);
hb(s,'先看原来正确的部分有没有受影响','内容不能少读或多读，原来通过的检查还要继续通过。\n这一句和前后句的连接也要重新检查。',64,320,1110,28);
hb(s,'再看这次修改有没有解决问题','程序确认有改善，才采用新版本。没有改善就继续保留原件。\n像“声音是否适合人物”这样的问题，仍要靠人试听。',64,479,1110,27);
foot(s,'只修一个问题段，也要一起检查它的前后两句');

// 18
s=page(18,'具体例子：读完又重复，怎样安全去掉');
table(s,[['先确认什么','然后怎样处理'],['原文应该读的部分已经完整读完','找正文与多余重复之间的停顿'],['前半段内容完整，后半段只有多余重复','把两部分分别转成文字，再次核对'],['切的位置不会伤到正常发音','两边留出 0.1 秒保护，只去掉多余尾段']],{y:183,h:270,widths:[545,607],size:26});
a=node(s,'原文该读的部分\n完整保留',100,507,480,84,C.green);
b=node(s,'多出来的重复\n确认后再去掉',725,507,350,84);link(s,a,b);
text(s,'停顿处切开',592,466,180,36,23,C.blue,true);
foot(s,'默认先让人复核，只有条件明确且用户开启自动处理时才自动采用');

// 19
s=page(19,'原音和修改版都保存，随时能查清改了什么');
a=node(s,'生成时\n记下正文和声音设置',64,193,300,94);
b=node(s,'生成后\n保存原始录音',490,193,300,94);
c=node(s,'修改后\n另存新版本和修改记录',916,193,300,94);link(s,a,b);link(s,b,c);
hb(s,'同样的内容和设置，可以复用已有录音','调语速、剪重复等处理另存文件，原来的录音不会被覆盖。\n最后按顺序拼成整章，并检查音频和检查单是否对应。',64,359,1110,28);
text(s,'例如：R039 去掉多余重复后，仍能找到修改前的录音进行比较。',64,544,1150,60,28,C.blue,true);
foot(s,'每份文件都有唯一校验记录，避免拿旧音频的试听结论套在新版本上');

// 20
s=page(20,'实际完成的案例：《Flipped》首章');
[['14,311','原文字符'],['5','人物与角色'],['100','生成的小段'],['99','小段连接处']].forEach(([v,l],i)=>{
 text(s,v,64+i*300,191,280,90,61,C.blue,true);text(s,l,67+i*300,294,270,45,27,C.muted);
});
table(s,[['阶段','已经做了什么'],['首次生成','完成约 15 分 32 秒的原始版本，保留原音频'],['调整 Bryce 声音','根据已确认的参考音，增加 67 次生成请求'],['修正具体问题','处理重复和长停顿等问题，最新版本约 17 分 34 秒']],{y:393,h:205,widths:[240,912],size:25});
foot(s,'版本时长不同，不能直接说明谁更好，已确认的局部也不代表整章全部通过');

// 21
s=page(21,'哪些问题已经试听确认修好了');
table(s,[['问题位置','做了什么修改','已经确认的范围'],['R039 句尾重复','留下完整正文，删多余重复','保留的正常语音没改，局部试听通过'],['R018 多读 No','只留下原文要求的三次 No','前后片段已核对，局部试听通过'],['J076 停顿太长','只剪掉多余的无声部分','两句之间约 1 秒，试听通过'],['R034 开头反复读','C’mon 改用 Come on! 来读','发音及与前后句的连接试听通过']],{y:181,h:350,widths:[250,440,462],size:25});
text(s,'已保存 10 个试听接受的修复案例，全部来自同一本书的同一章。',64,559,1150,58,29,C.blue,true);
foot(s,'这些案例能说明具体怎么修，还不能算出对其他书籍的修复成功率');

// 22
s=page(22,'让人少重复听，接下来再验证人物好不好认');
a=node(s,'133 条问题提示',64,186,265,85);
b=node(s,'整理为 48 个片段',485,186,265,85);
c=node(s,'合成 9 段试听内容',906,186,310,85);link(s,a,b);link(s,b,c);
hb(s,'同一段录音被反复提示，就合在一起听','每个问题都保留，只合并重复的试听范围。\n原来重叠片段加起来约 27 分钟，合并后约 16 分钟。',64,326,1110,27);
hb(s,'“听出是谁”的题目已经准备好','36 道题，使用九段已做试听检查的录音。\n目前还没有听众答题结果，不能说自动分配已经更容易辨认。',64,482,1110,27);
foot(s,'本批自动分配与随机分配恰好相同，不能用这批材料比较二者优劣');

// 23
s=page(23,'网页操作保护：重新拆分后，要重新确认');
a=node(s,'上传书籍\n选择要做的章节',64,200,235,94);
b=node(s,'重新拆分文字\n旧的确认立即失效',368,200,235,94);
c=node(s,'检查人物和声音\n重新点击确认',672,200,235,94);
let d=node(s,'开始生成\n查看和下载结果',976,200,235,94);link(s,a,b);link(s,b,c);link(s,c,d);
hb(s,'避免“内容已改，仍按旧安排生成”','重新拆分时，不能拿上一次的确认继续生成。\n同一本书的保存、确认和开始生成，程序会协调顺序，避免互相冲突。',64,370,1110,28);
text(s,'关闭进度显示，也不会把仍在工作的任务误当成已经结束。',64,548,1140,58,29,C.blue,true);
foot(s,'后台流程已经测试，新控件在浏览器中的实际操作体验仍需最后确认');

// 24
s=page(24,'现在做到哪一步，接下来先做什么');
table(s,[['方面','目前已经做了','下一步'],['整套制作流程','选章节、分人物、选声音、生成和查问题','先把 MiMo 网页使用流程做好'],['实际使用','完成首章生成，修过重复和长停顿等问题','完成这一版整章试听，再扩大使用'],['研究准备','有修复案例，也有 36 道人物辨认题','换更多书，找听众做比较'],['其他语音服务','原转换器支持多种服务','新的适配与论文实验暂缓']],{y:178,h:347,widths:[210,530,412],size:25});
text(s,'最近保存的程序测试：674 项，644 项通过，30 项因环境跳过。',64,558,1150,53,28,C.blue,true);
foot(s,'程序测试说明功能运行情况，实际听感和论文效果还需要另外验证');

const after=await p.inspect({select:'$.slides[*]',include:['id','index','title','elements.text','elements.kind']});
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
