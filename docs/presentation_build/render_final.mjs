import fs from 'node:fs/promises';import {PresentationFile,FileBlob} from '@oai/artifact-tool';
let root='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/docs';let p=await PresentationFile.importPptx(await FileBlob.load(root+'/presentation_output/多角色有声书_项目汇报与前沿研究_定稿.pptx'));
for(let i=0;i<p.slides.items.length;i++){let b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(root+`/presentation_build/renders/final-${String(i+1).padStart(2,'0')}.png`,new Uint8Array(await b.arrayBuffer()));}console.log('Final slides rendered:',p.slides.items.length);
