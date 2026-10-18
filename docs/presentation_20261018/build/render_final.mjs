import fs from 'node:fs/promises';
import path from 'node:path';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const work='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/docs/presentation_20261018';
const file=path.join(work,'output/多角色有声书_项目进展与创新实现_20261018.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(file));
const out=path.join(work,'build/final_renders');
await fs.mkdir(out,{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(out,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));
}
console.log('Rendered final',p.slides.items.length);
