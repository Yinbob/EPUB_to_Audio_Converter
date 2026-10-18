import sharp from 'sharp'; import fs from 'node:fs/promises';
let dir='/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1/docs/presentation_build/renders';
for(let k=0;k<4;k++){let items=[];for(let j=0;j<6;j++){let n=k*6+j+1;if(n>22)break;let b=await sharp(`${dir}/slide-${String(n).padStart(2,'0')}.png`).resize(640,360).toBuffer();items.push({input:b,left:(j%2)*640,top:Math.floor(j/2)*360});}await sharp({create:{width:1280,height:1080,channels:3,background:'#ccc'}}).composite(items).png().toFile(`${dir}/montage-${k}.png`);}
