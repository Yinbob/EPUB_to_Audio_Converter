# 英文真实书籍候选：原文与归属核对

本材料仅离线提取；尚未选定正式研究语料，没有调用模型或生成音频。仓库原EPUB保持不变。
来源：The Life and Adventures of Robinson Crusoe，Daniel Defoe。小说正文为转换编号2～21，共20章；原解析器另列前言、版权和目录。
本文的“第几章”均使用转换编号，定位按解析后文本的Unicode字符区间。引号密集只表示取样特征，不等于多角色对话已确认。
当前10个候选、40个连续单位，属于同一本书；不能作为10个独立书籍来源。四单位划分是工程草稿，确认说话人后仍可能需要重新分段，实际合成请求数另行预检。
全书角色对白量排名需要完整的全书归属核验，本候选不能替代；尚未分配或沿用Morgan/Taylor的身份参考。
第一人称叙述如何与主人公对白共用声音，需要在正式角色档案中明确，再固定下来。

## 核对顺序

1. 先确定是否采用这部书。
2. 核对各段连续原文及上下文；补充说话人、别名及不确定归属。不要仅按引号自动定人。
3. 再生成有版本的角色剧本和请求计划，先做少量真实章节片段验证；描述声音需独立先导与人工参考。
4. 音频生成后，依次检查拼接、同角色一致性、重复漏读及多读、信号与响度。当前没有任何音频人工标签。

## 候选原文

### R01 · 转换第2章 · CHAPTER_I_START_IN_LIFE

原文区间 [186, 591)；取样特征 `narration`；说话人待核验。

**前文**：CHAPTER I. START IN LIFE I was born in the year 1632, in the city of York, of a good family, though not of that country, my father being a foreigner of Bremen, who settled first at Hull.

**本段连续原文**： He got a good estate by merchandise, and leaving off his trade, lived afterwards at York, from whence he had married my mother, whose relations were named Robinson, a very good family in that country, and from whom I was called Robinson Kreutznaer; but, by the usual corruption of words in England, we are now called—nay we call ourselves and write our name—Crusoe; and so my companions always called me.

**后文**： I had two elder brothers, one of whom was lieutenant-colonel to an English regiment of foot in Flanders, formerly commanded by the famous Colonel Lockhart, and was killed at the battle near Dunkirk against the Spaniards. What became of my second bro

分段草稿：

- R01_1 [186, 276)： He got a good estate by merchandise, and leaving off his trade, lived afterwards at York,（角色未分配）
- R01_2 [276, 387)： from whence he had married my mother, whose relations were named Robinson, a very good family in that country,（角色未分配）
- R01_3 [387, 485)： and from whom I was called Robinson Kreutznaer; but, by the usual corruption of words in England,（角色未分配）
- R01_4 [485, 591)： we are now called—nay we call ourselves and write our name—Crusoe; and so my companions always called me.（角色未分配）

### R02 · 转换第4章 · CHAPTER_III_WRECKED_ON_A_DESERT_ISLAND

原文区间 [39, 268)；取样特征 `narration`；说话人待核验。

**前文**：CHAPTER III. WRECKED ON A DESERT ISLAND

**本段连续原文**： After this stop, we made on to the southward continually for ten or twelve days, living very sparingly on our provisions, which began to abate very much, and going no oftener to the shore than we were obliged to for fresh water.

**后文**： My design in this was to make the river Gambia or Senegal, that is to say anywhere about the Cape de Verde, where I was in hopes to meet with some European ship; and if I did not, I knew not what course I had to take, but to seek for the islands, or

分段草稿：

- R02_1 [39, 120)： After this stop, we made on to the southward continually for ten or twelve days,（角色未分配）
- R02_2 [120, 161)： living very sparingly on our provisions,（角色未分配）
- R02_3 [161, 193)： which began to abate very much,（角色未分配）
- R02_4 [193, 268)： and going no oftener to the shore than we were obliged to for fresh water.（角色未分配）

### R03 · 转换第2章 · CHAPTER_I_START_IN_LIFE

原文区间 [9243, 9920)；取样特征 `digits`；说话人待核验。

**前文**：e, though, in the meantime, I continued obstinately deaf to all proposals of settling to business, and frequently expostulated with my father and mother about their being so positively determined against what they knew my inclinations prompted me to.

**本段连续原文**： But being one day at Hull, where I went casually, and without any purpose of making an elopement at that time; but, I say, being there, and one of my companions being about to sail to London in his father’s ship, and prompting me to go with them with the common allurement of seafaring men, that it should cost me nothing for my passage, I consulted neither father nor mother any more, nor so much as sent them word of it; but leaving them to hear of it as they might, without asking God’s blessing or my father’s, without any consideration of circumstances or consequences, and in an ill hour, God knows, on the 1st of September 1651, I went on board a ship bound for London.

**后文**： Never any young adventurer’s misfortunes, I believe, began sooner, or continued longer than mine. The ship was no sooner out of the Humber than the wind began to blow and the sea to rise in a most frightful manner; and, as I had never been at sea be

分段草稿：

- R03_1 [9243, 9379)： But being one day at Hull, where I went casually, and without any purpose of making an elopement at that time; but, I say, being there,（角色未分配）
- R03_2 [9379, 9581)： and one of my companions being about to sail to London in his father’s ship, and prompting me to go with them with the common allurement of seafaring men, that it should cost me nothing for my passage,（角色未分配）
- R03_3 [9581, 9758)： I consulted neither father nor mother any more, nor so much as sent them word of it; but leaving them to hear of it as they might, without asking God’s blessing or my father’s,（角色未分配）
- R03_4 [9758, 9920)： without any consideration of circumstances or consequences, and in an ill hour, God knows, on the 1st of September 1651, I went on board a ship bound for London.（角色未分配）

### R04 · 转换第6章 · CHAPTER_V_BUILDS_A_HOUSETHE_JOURNAL

原文区间 [37, 313)；取样特征 `digits`；说话人待核验。

**前文**：CHAPTER V. BUILDS A HOUSE—THE JOURNAL

**本段连续原文**： September 30, 1659.—I, poor miserable Robinson Crusoe, being shipwrecked during a dreadful storm in the offing, came on shore on this dismal, unfortunate island, which I called “The Island of Despair”; all the rest of the ship’s company being drowned, and myself almost dead.

**后文**： All the rest of the day I spent in afflicting myself at the dismal circumstances I was brought to—viz. I had neither food, house, clothes, weapon, nor place to fly to; and in despair of any relief, saw nothing but death before me—either that I shoul

分段草稿：

- R04_1 [37, 92)： September 30, 1659.—I, poor miserable Robinson Crusoe,（角色未分配）
- R04_2 [92, 179)： being shipwrecked during a dreadful storm in the offing, came on shore on this dismal,（角色未分配）
- R04_3 [179, 239)： unfortunate island, which I called “The Island of Despair”;（角色未分配）
- R04_4 [239, 313)： all the rest of the ship’s company being drowned, and myself almost dead.（角色未分配）

### R05 · 转换第3章 · CHAPTER_II_SLAVERY_AND_ESCAPE

原文区间 [11605, 12228)；取样特征 `quotes`；说话人待核验。

**前文**：r, into the boat. I knew where my patron’s case of bottles stood, which it was evident, by the make, were taken out of some English prize, and I conveyed them into the boat while the Moor was on shore, as if they had been there before for our master.

**本段连续原文**： I conveyed also a great lump of beeswax into the boat, which weighed about half a hundred-weight, with a parcel of twine or thread, a hatchet, a saw, and a hammer, all of which were of great use to us afterwards, especially the wax, to make candles. Another trick I tried upon him, which he innocently came into also: his name was Ismael, which they call Muley, or Moely; so I called to him—“Moely,” said I, “our patron’s guns are on board the boat; can you not get a little powder and shot? It may be we may kill some alcamies (a fowl like our curlews) for ourselves, for I know he keeps the gunner’s stores in the ship.”

**后文**： “Yes,” says he, “I’ll bring some;” and accordingly he brought a great leather pouch, which held a pound and a half of powder, or rather more; and another with shot, that had five or six pounds, with some bullets, and put all into the boat. At the sa

分段草稿：

- R05_1 [11605, 11755)： I conveyed also a great lump of beeswax into the boat, which weighed about half a hundred-weight, with a parcel of twine or thread, a hatchet, a saw,（角色未分配）
- R05_2 [11755, 11944)： and a hammer, all of which were of great use to us afterwards, especially the wax, to make candles. Another trick I tried upon him, which he innocently came into also: his name was Ismael,（角色未分配）
- R05_3 [11944, 12013)： which they call Muley, or Moely; so I called to him—“Moely,” said I,（角色未分配）
- R05_4 [12013, 12228)： “our patron’s guns are on board the boat; can you not get a little powder and shot? It may be we may kill some alcamies (a fowl like our curlews) for ourselves, for I know he keeps the gunner’s stores in the ship.”（角色未分配）

### R06 · 转换第16章 · CHAPTER_XV_FRIDAYS_EDUCATION

原文区间 [30, 649)；取样特征 `quotes`；说话人待核验。

**前文**：CHAPTER XV. FRIDAY’S EDUCATION

**本段连续原文**： After I had been two or three days returned to my castle, I thought that, in order to bring Friday off from his horrid way of feeding, and from the relish of a cannibal’s stomach, I ought to let him taste other flesh; so I took him out with me one morning to the woods. I went, indeed, intending to kill a kid out of my own flock; and bring it home and dress it; but as I was going I saw a she-goat lying down in the shade, and two young kids sitting by her. I catched hold of Friday. “Hold,” said I, “stand still;” and made signs to him not to stir: immediately I presented my piece, shot, and killed one of the kids.

**后文**： The poor creature, who had at a distance, indeed, seen me kill the savage, his enemy, but did not know, nor could imagine how it was done, was sensibly surprised, trembled, and shook, and looked so amazed that I thought he would have sunk down. He d

分段草稿：

- R06_1 [30, 165)： After I had been two or three days returned to my castle, I thought that, in order to bring Friday off from his horrid way of feeding,（角色未分配）
- R06_2 [165, 361)： and from the relish of a cannibal’s stomach, I ought to let him taste other flesh; so I took him out with me one morning to the woods. I went, indeed, intending to kill a kid out of my own flock;（角色未分配）
- R06_3 [361, 489)： and bring it home and dress it; but as I was going I saw a she-goat lying down in the shade, and two young kids sitting by her.（角色未分配）
- R06_4 [489, 649)： I catched hold of Friday. “Hold,” said I, “stand still;” and made signs to him not to stir: immediately I presented my piece, shot, and killed one of the kids.（角色未分配）

### R07 · 转换第17章 · CHAPTER_XVI_RESCUE_OF_PRISONERS_FROM_CANNIBALS

原文区间 [47, 566)；取样特征 `quotes`；说话人待核验。

**前文**：CHAPTER XVI. RESCUE OF PRISONERS FROM CANNIBALS

**本段连续原文**： Upon the whole, I was by this time so fixed upon my design of going over with him to the continent that I told him we would go and make one as big as that, and he should go home in it. He answered not one word, but looked very grave and sad. I asked him what was the matter with him. He asked me again, “Why you angry mad with Friday?—what me done?” I asked him what he meant. I told him I was not angry with him at all. “No angry!” says he, repeating the words several times; “why send Friday home away to my nation?”

**后文**： “Why,” says I, “Friday, did not you say you wished you were there?” “Yes, yes,” says he, “wish we both there; no wish Friday there, no master there.” In a word, he would not think of going there without me. “I go there, Friday?” says I; “what shall 

分段草稿：

- R07_1 [47, 203)： Upon the whole, I was by this time so fixed upon my design of going over with him to the continent that I told him we would go and make one as big as that,（角色未分配）
- R07_2 [203, 289)： and he should go home in it. He answered not one word, but looked very grave and sad.（角色未分配）
- R07_3 [289, 424)： I asked him what was the matter with him. He asked me again, “Why you angry mad with Friday?—what me done?” I asked him what he meant.（角色未分配）
- R07_4 [424, 566)： I told him I was not angry with him at all. “No angry!” says he, repeating the words several times; “why send Friday home away to my nation?”（角色未分配）

### R08 · 转换第18章 · CHAPTER_XVII_VISIT_OF_MUTINEERS

原文区间 [16436, 16723)；取样特征 `quotes`；说话人待核验。

**前文**： perceive using the most passionate gestures of entreaty, affliction, and despair, even to a kind of extravagance; the other two, I could perceive, lifted up their hands sometimes, and appeared concerned indeed, but not to such a degree as the first.

**本段连续原文**： I was perfectly confounded at the sight, and knew not what the meaning of it should be. Friday called out to me in English, as well as he could, “O master! you see English mans eat prisoner as well as savage mans.” “Why, Friday,” says I, “do you think they are going to eat them, then?”

**后文**： “Yes,” says Friday, “they will eat them.” “No no,” says I, “Friday; I am afraid they will murder them, indeed; but you may be sure they will not eat them.” All this while I had no thought of what the matter really was, but stood trembling with the h

分段草稿：

- R08_1 [16436, 16524)： I was perfectly confounded at the sight, and knew not what the meaning of it should be.（角色未分配）
- R08_2 [16524, 16581)： Friday called out to me in English, as well as he could,（角色未分配）
- R08_3 [16581, 16651)： “O master! you see English mans eat prisoner as well as savage mans.”（角色未分配）
- R08_4 [16651, 16723)： “Why, Friday,” says I, “do you think they are going to eat them, then?”（角色未分配）

### R09 · 转换第19章 · CHAPTER_XVIII_THE_SHIP_RECOVERED

原文区间 [1686, 2325)；取样特征 `quotes`；说话人待核验。

**前文**：in, who it seems was the chief officer among them, and all the rest, they were as outrageous as any of the ship’s crew, and were no doubt made desperate in their new enterprise; and terribly apprehensive he was that they would be too powerful for us.

**本段连续原文**： I smiled at him, and told him that men in our circumstances were past the operation of fear; that seeing almost every condition that could be was better than that which we were supposed to be in, we ought to expect that the consequence, whether death or life, would be sure to be a deliverance. I asked him what he thought of the circumstances of my life, and whether a deliverance were not worth venturing for? “And where, sir,” said I, “is your belief of my being preserved here on purpose to save your life, which elevated you a little while ago? For my part,” said I, “there seems to be but one thing amiss in all the prospect of it.”

**后文**： “What is that?” say he. “Why,” said I, “it is, that as you say there are three or four honest fellows among them which should be spared, had they been all of the wicked part of the crew I should have thought God’s providence had singled them out to 

分段草稿：

- R09_1 [1686, 1882)： I smiled at him, and told him that men in our circumstances were past the operation of fear; that seeing almost every condition that could be was better than that which we were supposed to be in,（角色未分配）
- R09_2 [1882, 1981)： we ought to expect that the consequence, whether death or life, would be sure to be a deliverance.（角色未分配）
- R09_3 [1981, 2124)： I asked him what he thought of the circumstances of my life, and whether a deliverance were not worth venturing for? “And where, sir,” said I,（角色未分配）
- R09_4 [2124, 2325)： “is your belief of my being preserved here on purpose to save your life, which elevated you a little while ago? For my part,” said I, “there seems to be but one thing amiss in all the prospect of it.”（角色未分配）

### R10 · 转换第21章 · CHAPTER_XX_FIGHT_BETWEEN_FRIDAY_AND_A_BEAR

原文区间 [1507, 2049)；取样特征 `quotes`；说话人待核验。

**前文**：pursue his revenge, and will have satisfaction in point of honour—that is his first quality: the next is, if he be once affronted, he will never leave you, night or day, till he has his revenge, but follows at a good round rate till he overtakes you.

**本段连续原文**： My man Friday had delivered our guide, and when we came up to him he was helping him off his horse, for the man was both hurt and frightened, when on a sudden we espied the bear come out of the wood; and a monstrous one it was, the biggest by far that ever I saw. We were all a little surprised when we saw him; but when Friday saw him, it was easy to see joy and courage in the fellow’s countenance. “O! O! O!” says Friday, three times, pointing to him; “O master, you give me te leave, me shakee te hand with him; me makee you good laugh.”

**后文**： I was surprised to see the fellow so well pleased. “You fool,” says I, “he will eat you up.”—“Eatee me up! eatee me up!” says Friday, twice over again; “me eatee him up; me makee you good laugh; you all stay here, me show you good laugh.” So down he

分段草稿：

- R10_1 [1507, 1649)： My man Friday had delivered our guide, and when we came up to him he was helping him off his horse, for the man was both hurt and frightened,（角色未分配）
- R10_2 [1649, 1771)： when on a sudden we espied the bear come out of the wood; and a monstrous one it was, the biggest by far that ever I saw.（角色未分配）
- R10_3 [1771, 1908)： We were all a little surprised when we saw him; but when Friday saw him, it was easy to see joy and courage in the fellow’s countenance.（角色未分配）
- R10_4 [1908, 2049)： “O! O! O!” says Friday, three times, pointing to him; “O master, you give me te leave, me shakee te hand with him; me makee you good laugh.”（角色未分配）

