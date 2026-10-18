# 待人工标注的 MiMo 样本

编辑 [annotation.csv](annotation.csv)，按拼接、一致性、内容完整性的顺序试听。所有判断初始为空；填写 yes/no/uncertain/not_applicable，空白表示未检查。正常角色切换不算音色漂移；缺少同角色参考时填 uncertain 或 not_applicable，不凭单段判断跨段一致性。

review_status 使用 pending/reviewed/needs_review。已完成需填写 reviewer 和含时区的 ISO reviewed_at，例如 2026-10-16T12:00:00+08:00；notes 记录问题秒数和文字。

边界四列 click/cutoff/overlap/gap 全部明确判断后才能标 reviewed；labels_json 用 JSON 数组，对应 boundary_click_suspected/cutoff_suspected/overlap/unexpected_gap。只有四项都 no 才填 []。有疑点保持 needs_review，不把未知当正常。完整片段的 labels_json 留空。

人工结果用 import-review 导入，未标注记录不会进入训练；导出不自动划分 train/dev/test。相同 group_id 的所有变体应保留在同一划分。本包只提供材料，不证明检测或修复效果；章节、父块、修复子块、窗口音频相互重叠，不能按文件数统计独立样本。scope_kind 与 parent_chunk_id 标明修复子块及新增内部接缝；这些受保护字段不要修改。

### C000005_001 · 完整片段 · narrator

[试听](audio/C000005_001.wav)

原文：Diving Under All I've ever wanted is for Juli Baker to leave me alone. For her to back off — you know, just give me some space. It all started the summer before second grade when our moving van pulled into her neighborhood.

预期读法：Diving Under All I've ever wanted is for Juli Baker to leave me alone. For her to back off — you know, just give me some space. It all started the summer before second grade when our moving van pulled into her neighborhood.

### C000005_002 · 完整片段 · narrator

[试听](audio/C000005_002.wav)

原文： And since we're now about done with the eighth grade, that, my friend, makes more than half a decade of strategic avoidance and social discomfort. She didn't just barge into my life. She barged and shoved and wedged her way into my life.

预期读法： And since we're now about done with the eighth grade, that, my friend, makes more than half a decade of strategic avoidance and social discomfort. She didn't just barge into my life. She barged and shoved and wedged her way into my life.

### C000005_003 · 完整片段 · narrator

[试听](audio/C000005_003.wav)

原文： Did we invite her to get into our moving van and start climbing all over boxes? No! But that's exactly what she did, taking over and showing off like only Juli Baker can. My dad tried to stop her. 

预期读法： Did we invite her to get into our moving van and start climbing all over boxes? No! But that's exactly what she did, taking over and showing off like only Juli Baker can. My dad tried to stop her. 

### C000005_004 · 完整片段 · bryce_father

[试听](audio/C000005_004.wav)

原文：“Hey!”

预期读法：“Hey!”

### C000005_005 · 完整片段 · narrator

[试听](audio/C000005_005.wav)

原文： he says as she's catapulting herself on board. 

预期读法： he says as she's catapulting herself on board. 

### C000005_006 · 完整片段 · bryce_father

[试听](audio/C000005_006.wav)

原文：“What are you doing? You're getting mud everywhere!”

预期读法：“What are you doing? You're getting mud everywhere!”

### C000005_007 · 完整片段 · narrator

[试听](audio/C000005_007.wav)

原文： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

预期读法： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

### C000005_008 · 完整片段 · juli

[试听](audio/C000005_008.wav)

原文：“Don't you want some help?”

预期读法：“Don't you want some help?”

### C000005_009 · 完整片段 · narrator

[试听](audio/C000005_009.wav)

原文： She glanced my way. 

预期读法： She glanced my way. 

### C000005_010 · 完整片段 · juli

[试听](audio/C000005_010.wav)

原文：“It sure looks like you need it.”

预期读法：“It sure looks like you need it.”

### C000005_011 · 完整片段 · narrator

[试听](audio/C000005_011.wav)

原文： I didn't like the implication. And even though my dad had been tossing me the same sort of look all week, I could tell — he didn't like this girl either. 

预期读法： I didn't like the implication. And even though my dad had been tossing me the same sort of look all week, I could tell — he didn't like this girl either. 

### C000005_012 · 完整片段 · bryce_father

[试听](audio/C000005_012.wav)

原文：“Hey! Don't do that,”

预期读法：“Hey! Don't do that,”

### C000005_013 · 完整片段 · narrator

[试听](audio/C000005_013.wav)

原文： he warned her. 

预期读法： he warned her. 

### C000005_014 · 完整片段 · bryce_father

[试听](audio/C000005_014.wav)

原文：“There are some really valuable things in that box.”

预期读法：“There are some really valuable things in that box.”

### C000005_015 · 完整片段 · juli

[试听](audio/C000005_015.wav)

原文：“Oh. Well, how about this one?”

预期读法：“Oh. Well, how about this one?”

### C000005_016 · 完整片段 · narrator

[试听](audio/C000005_016.wav)

原文： She scoots over to a box labeled LENOX and looks my way again. 

预期读法： She scoots over to a box labeled LENOX and looks my way again. 

### C000005_017 · 完整片段 · juli

[试听](audio/C000005_017.wav)

原文：“We should push it together!”

预期读法：“We should push it together!”

### C000005_018 · 完整片段 · bryce_father

[试听](audio/C000005_018.wav)

原文：“No, no, no!”

预期读法：“No, no, no!”

### C000005_019 · 完整片段 · narrator

[试听](audio/C000005_019.wav)

原文： my dad says, then pulls her up by the arm. 

预期读法： my dad says, then pulls her up by the arm. 

### C000005_020 · 完整片段 · bryce_father

[试听](audio/C000005_020.wav)

原文：“Why don't you run along home? Your mother's probably wondering where you are.”

预期读法：“Why don't you run along home? Your mother's probably wondering where you are.”

### C000005_021 · 完整片段 · narrator

[试听](audio/C000005_021.wav)

原文： This was the beginning of my soon-to-become-acute awareness that the girl cannot take a hint. Of any kind. Does she zip on home like a kid should when they've been invited to leave? No. She says, 

预期读法： This was the beginning of my soon-to-become-acute awareness that the girl cannot take a hint. Of any kind. Does she zip on home like a kid should when they've been invited to leave? No. She says, 

### C000005_022 · 完整片段 · juli

[试听](audio/C000005_022.wav)

原文：“Oh, my mom knows where I am. She said it was fine.”

预期读法：“Oh, my mom knows where I am. She said it was fine.”

### C000005_023 · 完整片段 · narrator

[试听](audio/C000005_023.wav)

原文： Then she points across the street and says, 

预期读法： Then she points across the street and says, 

### C000005_024 · 完整片段 · juli

[试听](audio/C000005_024.wav)

原文：“We just live right over there.”

预期读法：“We just live right over there.”

### C000005_025 · 完整片段 · narrator

[试听](audio/C000005_025.wav)

原文： My father looks to where she's pointing and mutters, 

预期读法： My father looks to where she's pointing and mutters, 

### C000005_026 · 完整片段 · bryce_father

[试听](audio/C000005_026.wav)

原文：“Oh boy.”

预期读法：“Oh boy.”

### C000005_027 · 完整片段 · narrator

[试听](audio/C000005_027.wav)

原文： Then he looks at me and winks as he says, 

预期读法： Then he looks at me and winks as he says, 

### C000005_028 · 完整片段 · bryce_father

[试听](audio/C000005_028.wav)

原文：“Bryce, isn't it time for you to go inside and help your mother?”

预期读法：“Bryce, isn't it time for you to go inside and help your mother?”

### C000005_029 · 完整片段 · narrator

[试听](audio/C000005_029.wav)

原文： I knew right off that this was a ditch play. And I didn't think about it until later, but ditch wasn't a play I'd run with my dad before. Face it, pulling a ditch is not something discussed with dads.

预期读法： I knew right off that this was a ditch play. And I didn't think about it until later, but ditch wasn't a play I'd run with my dad before. Face it, pulling a ditch is not something discussed with dads.

### C000005_030 · 完整片段 · narrator

[试听](audio/C000005_030.wav)

原文： It's like, against parental law to tell your kid it's okay to ditch someone, no matter how annoying or muddy they might be. But there he was, putting the play in motion, and man, he didn't have to wink twice. I smiled and said, “Sure thing!

预期读法： It's like, against parental law to tell your kid it's okay to ditch someone, no matter how annoying or muddy they might be. But there he was, putting the play in motion, and man, he didn't have to wink twice. I smiled and said, “Sure thing!

### C000005_031 · 完整片段 · narrator

[试听](audio/C000005_031.wav)

原文：” then jumped off the liftgate and headed for my new front door. I heard her coming after me but I couldn't believe it. Maybe it just sounded like she was chasing me; maybe she was really going the other way.

预期读法：” then jumped off the liftgate and headed for my new front door. I heard her coming after me but I couldn't believe it. Maybe it just sounded like she was chasing me; maybe she was really going the other way.

### C000005_032 · 完整片段 · narrator

[试听](audio/C000005_032.wav)

原文： But before I got up the nerve to look, she blasted right past me, grabbing my arm and yanking me along. This was too much. I planted myself and was about to tell her to get lost when the weirdest thing happened.

预期读法： But before I got up the nerve to look, she blasted right past me, grabbing my arm and yanking me along. This was too much. I planted myself and was about to tell her to get lost when the weirdest thing happened.

### C000005_033 · 完整片段 · narrator

[试听](audio/C000005_033.wav)

原文： I was making this big windmill motion to break away from her, but somehow on the downswing my hand wound up tangling into hers. I couldn't believe it. There I was, holding the mud monkey's hand! I tried to shake her off, but she just clamped on tight and yanked me along, saying, 

预期读法： I was making this big windmill motion to break away from her, but somehow on the downswing my hand wound up tangling into hers. I couldn't believe it. There I was, holding the mud monkey's hand! I tried to shake her off, but she just clamped on tight and yanked me along, saying, 

### C000005_034 · 完整片段 · juli

[试听](audio/C000005_034.wav)

原文：“C'mon!”

预期读法：“C'mon!”

### C000005_035 · 完整片段 · narrator

[试听](audio/C000005_035.wav)

原文： My mom came out of the house and immediately got the world's sappiest look on her face. 

预期读法： My mom came out of the house and immediately got the world's sappiest look on her face. 

### C000005_036 · 完整片段 · bryce_mother

[试听](audio/C000005_036.wav)

原文：“Well, hello,”

预期读法：“Well, hello,”

### C000005_037 · 完整片段 · narrator

[试听](audio/C000005_037.wav)

原文： she says to Juli. 

预期读法： she says to Juli. 

### C000005_038 · 完整片段 · juli

[试听](audio/C000005_038.wav)

原文：“Hi!”

预期读法：“Hi!”

### C000005_039 · 完整片段 · narrator

[试听](audio/C000005_039.wav)

原文： I'm still trying to pull free, but the girl's got me in a death grip. My mom's grinning, looking at our hands and my fiery red face. 

预期读法： I'm still trying to pull free, but the girl's got me in a death grip. My mom's grinning, looking at our hands and my fiery red face. 

### C000005_040 · 完整片段 · bryce_mother

[试听](audio/C000005_040.wav)

原文：“And what's your name, honey?”

预期读法：“And what's your name, honey?”

### C000005_041 · 完整片段 · juli

[试听](audio/C000005_041.wav)

原文：“Julianna Baker. I live right over there,”

预期读法：“Julianna Baker. I live right over there,”

### C000005_042 · 完整片段 · narrator

[试听](audio/C000005_042.wav)

原文： she says, pointing with her unoccupied hand. 

预期读法： she says, pointing with her unoccupied hand. 

### C000005_043 · 完整片段 · bryce_mother

[试听](audio/C000005_043.wav)

原文：“Well, I see you've met my son,”

预期读法：“Well, I see you've met my son,”

### C000005_044 · 完整片段 · narrator

[试听](audio/C000005_044.wav)

原文： she says, still grinning away. 

预期读法： she says, still grinning away. 

### C000005_045 · 完整片段 · juli

[试听](audio/C000005_045.wav)

原文：“Uh-huh!”

预期读法：“Uh-huh!”

### C000005_046 · 完整片段 · narrator

[试听](audio/C000005_046.wav)

原文： Finally I break free and do the only manly thing available when you're seven years old — I dive behind my mother. Mom puts her arm around me and says, 

预期读法： Finally I break free and do the only manly thing available when you're seven years old — I dive behind my mother. Mom puts her arm around me and says, 

### C000005_047 · 完整片段 · bryce_mother

[试听](audio/C000005_047.wav)

原文：“Bryce, honey, why don't you show Julianna around the house?”

预期读法：“Bryce, honey, why don't you show Julianna around the house?”

### C000005_048 · 完整片段 · narrator

[试听](audio/C000005_048.wav)

原文： I flash her help and warning signals with every part of my body, but she's not receiving. Then she shakes me off and says, 

预期读法： I flash her help and warning signals with every part of my body, but she's not receiving. Then she shakes me off and says, 

### C000005_049 · 完整片段 · bryce_mother

[试听](audio/C000005_049.wav)

原文：“Go on.”

预期读法：“Go on.”

### C000005_050 · 完整片段 · narrator

[试听](audio/C000005_050.wav)

原文： Juli would've tramped right in if my mother hadn't noticed her shoes and told her to take them off. And after those were off, my mom told her that her dirty socks had to go, too. Juli wasn't embarrassed. Not a bit. She just peeled them off and left them in a crusty heap on our porch.

预期读法： Juli would've tramped right in if my mother hadn't noticed her shoes and told her to take them off. And after those were off, my mom told her that her dirty socks had to go, too. Juli wasn't embarrassed. Not a bit. She just peeled them off and left them in a crusty heap on our porch.

### C000005_051 · 完整片段 · narrator

[试听](audio/C000005_051.wav)

原文： I didn't exactly give her a tour. I locked myself in the bathroom instead. And after about ten minutes of yelling back at her that no, I wasn't coming out anytime soon, things got quiet out in the hall. Another ten minutes went by before I got the nerve to peek out the door. No Juli.

预期读法： I didn't exactly give her a tour. I locked myself in the bathroom instead. And after about ten minutes of yelling back at her that no, I wasn't coming out anytime soon, things got quiet out in the hall. Another ten minutes went by before I got the nerve to peek out the door. No Juli.

### C000005_052 · 完整片段 · narrator

[试听](audio/C000005_052.wav)

原文： I snuck out and looked around, and yes! She was gone. Not a very sophisticated ditch, but hey, I was only seven. My troubles were far from over, though. Every day she came back, over and over again. 

预期读法： I snuck out and looked around, and yes! She was gone. Not a very sophisticated ditch, but hey, I was only seven. My troubles were far from over, though. Every day she came back, over and over again. 

### C000005_053 · 完整片段 · juli

[试听](audio/C000005_053.wav)

原文：“Can Bryce play?”

预期读法：“Can Bryce play?”

### C000005_054 · 完整片段 · narrator

[试听](audio/C000005_054.wav)

原文： I could hear her asking from my hiding place behind the couch. 

预期读法： I could hear her asking from my hiding place behind the couch. 

### C000005_055 · 完整片段 · juli

[试听](audio/C000005_055.wav)

原文：“Is he ready yet?”

预期读法：“Is he ready yet?”

### C000005_056 · 完整片段 · narrator

[试听](audio/C000005_056.wav)

原文： One time she even cut across the yard and looked through my window. I spotted her in the nick of time and dove under my bed, but man, that right there tells you something about Juli Baker. She's got no concept of personal space. No respect for privacy.

预期读法： One time she even cut across the yard and looked through my window. I spotted her in the nick of time and dove under my bed, but man, that right there tells you something about Juli Baker. She's got no concept of personal space. No respect for privacy.

### C000005_057 · 完整片段 · narrator

[试听](audio/C000005_057.wav)

原文： The world is her playground, and watch out below — Juli's on the slide! Lucky for me, my dad was willing to run block. And he did it over and over again. He told her I was busy or sleeping or just plain gone. He was a lifesaver. My sister, on the other hand, tried to sabotage me any chance she got.

预期读法： The world is her playground, and watch out below — Juli's on the slide! Lucky for me, my dad was willing to run block. And he did it over and over again. He told her I was busy or sleeping or just plain gone. He was a lifesaver. My sister, on the other hand, tried to sabotage me any chance she got.

### C000005_058 · 完整片段 · narrator

[试听](audio/C000005_058.wav)

原文： Lynetta's like that. She's four years older than me, and buddy, I've learned from watching her how not to run your life. She's got ANTAGONIZE written all over her. Just look at her — not cross-eyed or with your tongue sticking out or anything — just look at her and you've started an argument.

预期读法： Lynetta's like that. She's four years older than me, and buddy, I've learned from watching her how not to run your life. She's got ANTAGONIZE written all over her. Just look at her — not cross-eyed or with your tongue sticking out or anything — just look at her and you've started an argument.

### C000005_059 · 完整片段 · narrator

[试听](audio/C000005_059.wav)

原文： I used to knock-down-drag-out with her, but it's just not worth it. Girls don't fight fair. They pull your hair and gouge you and pinch you; then they run off gasping to mommy when you try and defend yourself with a fist. Then you get locked into time-out, and for what?

预期读法： I used to knock-down-drag-out with her, but it's just not worth it. Girls don't fight fair. They pull your hair and gouge you and pinch you; then they run off gasping to mommy when you try and defend yourself with a fist. Then you get locked into time-out, and for what?

### C000005_060 · 完整片段 · narrator

[试听](audio/C000005_060.wav)

原文： No, my friend, the secret is, don't snap at the bait. Let it dangle. Swim around it. Laugh it off. After a while they'll give up and try to lure someone else. At least that's the way it is with Lynetta.

预期读法： No, my friend, the secret is, don't snap at the bait. Let it dangle. Swim around it. Laugh it off. After a while they'll give up and try to lure someone else. At least that's the way it is with Lynetta.

### C000005_061 · 完整片段 · narrator

[试听](audio/C000005_061.wav)

原文： And the bonus of having her as a pain-in-the-rear sister was figuring out that this method works on everyone. Teachers, jerks at school, even Mom and Dad. Seriously. There's no winning arguments with your parents, so why get all pumped up over them?

预期读法： And the bonus of having her as a pain-in-the-rear sister was figuring out that this method works on everyone. Teachers, jerks at school, even Mom and Dad. Seriously. There's no winning arguments with your parents, so why get all pumped up over them?

### C000005_062 · 完整片段 · narrator

[试听](audio/C000005_062.wav)

原文： It is way better to dive down and get out of the way than it is to get clobbered by some parental tidal wave. The funny thing is, Lynetta's still clueless when it comes to dealing with Mom and Dad.

预期读法： It is way better to dive down and get out of the way than it is to get clobbered by some parental tidal wave. The funny thing is, Lynetta's still clueless when it comes to dealing with Mom and Dad.

### C000005_063 · 完整片段 · narrator

[试听](audio/C000005_063.wav)

原文： She goes straight into thrash mode and is too busy drowning in the argument to take a deep breath and dive for calmer water. And she thinks I'm stupid. Anyway, true to form, Lynetta tried to bait me with Juli those first few days.

预期读法： She goes straight into thrash mode and is too busy drowning in the argument to take a deep breath and dive for calmer water. And she thinks I'm stupid. Anyway, true to form, Lynetta tried to bait me with Juli those first few days.

### C000005_064 · 完整片段 · narrator

[试听](audio/C000005_064.wav)

原文： She even snuck her past Dad once and marched her all around the house, hunting me down. I wedged myself up on the top shelf of my closet, and lucky for me, neither of them looked up. A few minutes later I heard Dad yell at Juli to get off the antique furniture, and once again, she got booted.

预期读法： She even snuck her past Dad once and marched her all around the house, hunting me down. I wedged myself up on the top shelf of my closet, and lucky for me, neither of them looked up. A few minutes later I heard Dad yell at Juli to get off the antique furniture, and once again, she got booted.

### C000005_065 · 完整片段 · narrator

[试听](audio/C000005_065.wav)

原文： I don't think I went outside that whole first week. I helped unpack stuff and watched TV and just kind of hung around while my mom and dad arranged and rearranged the furniture, debating whether Empire settees and French Rococo tables should even be put in the same room.

预期读法： I don't think I went outside that whole first week. I helped unpack stuff and watched TV and just kind of hung around while my mom and dad arranged and rearranged the furniture, debating whether Empire settees and French Rococo tables should even be put in the same room.

### C000005_066 · 完整片段 · narrator

[试听](audio/C000005_066.wav)

原文： So believe me, I was dying to go outside. But every time I checked through the window, I could see Juli showing off in her yard. She'd be heading a soccer ball or doing high kicks with it or dribbling it up and down their driveway.

预期读法： So believe me, I was dying to go outside. But every time I checked through the window, I could see Juli showing off in her yard. She'd be heading a soccer ball or doing high kicks with it or dribbling it up and down their driveway.

### C000005_067 · 完整片段 · narrator

[试听](audio/C000005_067.wav)

原文： And when she wasn't busy showing off, she'd just sit on the curb with the ball between her feet, staring at our house. My mom didn't understand why it was so awful that “that cute little girl” had held my hand. She thought I should make friends with her. 

预期读法： And when she wasn't busy showing off, she'd just sit on the curb with the ball between her feet, staring at our house. My mom didn't understand why it was so awful that “that cute little girl” had held my hand. She thought I should make friends with her. 

### C000005_068 · 完整片段 · bryce_mother

[试听](audio/C000005_068.wav)

原文：“I thought you liked soccer, honey. Why don't you go out there and kick the ball around?”

预期读法：“I thought you liked soccer, honey. Why don't you go out there and kick the ball around?”

### C000005_069 · 完整片段 · narrator

[试听](audio/C000005_069.wav)

原文： Because I didn't want to be kicked around, that's why. And although I couldn't say it like that at the time, I still had enough sense at age seven and a half to know that Juli Baker was dangerous. Unavoidably dangerous, as it turns out.

预期读法： Because I didn't want to be kicked around, that's why. And although I couldn't say it like that at the time, I still had enough sense at age seven and a half to know that Juli Baker was dangerous. Unavoidably dangerous, as it turns out.

### C000005_070 · 完整片段 · narrator

[试听](audio/C000005_070.wav)

原文： The minute I walked into Mrs. Yelson's second-grade classroom, I was dead meat. 

预期读法： The minute I walked into Mrs. Yelson's second-grade classroom, I was dead meat. 

### C000005_071 · 完整片段 · juli

[试听](audio/C000005_071.wav)

原文：“Bryce!”

预期读法：“Bryce!”

### C000005_072 · 完整片段 · narrator

[试听](audio/C000005_072.wav)

原文： Juli squeals. 

预期读法： Juli squeals. 

### C000005_073 · 完整片段 · juli

[试听](audio/C000005_073.wav)

原文：“You're here.”

预期读法：“You're here.”

### C000005_074 · 完整片段 · narrator

[试听](audio/C000005_074.wav)

原文： Then she charges across the room and tackles me. Mrs. Yelson tried to explain this attack away as a “welcome hug,” but man, that was no hug. That was a front-line, take-'em-down tackle. And even though I shook her off, it was too late. I was branded for life. Everyone jeered, 

预期读法： Then she charges across the room and tackles me. Mrs. Yelson tried to explain this attack away as a “welcome hug,” but man, that was no hug. That was a front-line, take-'em-down tackle. And even though I shook her off, it was too late. I was branded for life. Everyone jeered, 

### C000005_075 · 完整片段 · classmates

[试听](audio/C000005_075.wav)

原文：“Where's your girl friend, Bryce?”

预期读法：“Where's your girl friend, Bryce?”

### C000005_076 · 完整片段 · classmates

[试听](audio/C000005_076.wav)

原文：“Are you married yet, Bryce?”

预期读法：“Are you married yet, Bryce?”

### C000005_077 · 完整片段 · narrator

[试听](audio/C000005_077.wav)

原文： And then when she chased me around at recess and tried to lay kisses on me, the whole school started singing, 

预期读法： And then when she chased me around at recess and tried to lay kisses on me, the whole school started singing, 

### C000005_078 · 完整片段 · classmates

[试听](audio/C000005_078.wav)

原文：“Bryce and Juli sitting in a tree, K-I-S-S-I-N-G…”

预期读法：“Bryce and Juli sitting in a tree, K-I-S-S-I-N-G…”

### C000005_079 · 完整片段 · narrator

[试听](audio/C000005_079.wav)

原文： My first year in town was a disaster. Third grade wasn't much better. She was still hot on my trail every time I turned around. Same with fourth. But then in fifth grade I took action. It started out slow — one of those Nah-that's-not-right ideas you get and forget.

预期读法： My first year in town was a disaster. Third grade wasn't much better. She was still hot on my trail every time I turned around. Same with fourth. But then in fifth grade I took action. It started out slow — one of those Nah-that's-not-right ideas you get and forget.

### C000005_080 · 完整片段 · narrator

[试听](audio/C000005_080.wav)

原文： But the more I played with the idea, the more I thought, What better way to ward Juli off? What better way to say to her, “Juli, you are not my type”? And so, my friend, I hatched the plan. I asked Shelly Stalls out.

预期读法： But the more I played with the idea, the more I thought, What better way to ward Juli off? What better way to say to her, “Juli, you are not my type”? And so, my friend, I hatched the plan. I asked Shelly Stalls out.

### C000005_081 · 完整片段 · narrator

[试听](audio/C000005_081.wav)

原文： To fully appreciate the brilliance of this, you have to understand that Juli hates Shelly Stalls. She always has, though it beats me why. Shelly's nice and she's friendly and she's got a lot of hair. What's not to like?

预期读法： To fully appreciate the brilliance of this, you have to understand that Juli hates Shelly Stalls. She always has, though it beats me why. Shelly's nice and she's friendly and she's got a lot of hair. What's not to like?

### C000005_082 · 完整片段 · narrator

[试听](audio/C000005_082.wav)

原文： But Juli hated her, and I was going to make this little gem of knowledge the solution to my problem. What I was thinking was that Shelly would eat lunch at our table and maybe walk around a little with me.

预期读法： But Juli hated her, and I was going to make this little gem of knowledge the solution to my problem. What I was thinking was that Shelly would eat lunch at our table and maybe walk around a little with me.

### C000005_083 · 完整片段 · narrator

[试听](audio/C000005_083.wav)

原文： That way, anytime Juli was around, all I'd have to do was hang a little closer to Shelly and things would just naturally take care of themselves. What happened, though, is that Shelly took things way too seriously. She went around telling everybody — including Juli — that we were in love.

预期读法： That way, anytime Juli was around, all I'd have to do was hang a little closer to Shelly and things would just naturally take care of themselves. What happened, though, is that Shelly took things way too seriously. She went around telling everybody — including Juli — that we were in love.

### C000005_084 · 完整片段 · narrator

[试听](audio/C000005_084.wav)

原文： In no time Juli and Shelly got into some kind of catfight, and while Shelly was recovering from that, my supposed friend Garrett — who had been totally behind this plan — told her what I was up to.

预期读法： In no time Juli and Shelly got into some kind of catfight, and while Shelly was recovering from that, my supposed friend Garrett — who had been totally behind this plan — told her what I was up to.

### C000005_085 · 完整片段 · narrator

[试听](audio/C000005_085.wav)

原文： He's always denied it, but I've since learned that his code of honor is easily corrupted by weepy females. That afternoon the principal tried cross-examining me, but I wouldn't cop to anything. I just kept telling her that I was sorry and that I really didn't understand what had happened.

预期读法： He's always denied it, but I've since learned that his code of honor is easily corrupted by weepy females. That afternoon the principal tried cross-examining me, but I wouldn't cop to anything. I just kept telling her that I was sorry and that I really didn't understand what had happened.

### C000005_086 · 完整片段 · narrator

[试听](audio/C000005_086.wav)

原文： Finally she let me go. Shelly cried for days and followed me around school sniffling and making me feel like a real jerk, which was even worse than having Juli as a shadow. Everything blew over at the one-week mark, though, when Shelly officially dumped me and started going out with Kyle Larsen.

预期读法： Finally she let me go. Shelly cried for days and followed me around school sniffling and making me feel like a real jerk, which was even worse than having Juli as a shadow. Everything blew over at the one-week mark, though, when Shelly officially dumped me and started going out with Kyle Larsen.

### C000005_087 · 完整片段 · narrator

[试听](audio/C000005_087.wav)

原文： Then Juli started up with the goo-goo eyes again, and I was back to square one. Now, in sixth grade things changed, though whether they improved is hard to say. I don't remember Juli actually chasing me in the sixth grade. But I do remember her sniffing me. Yes, my friend, I said sniffing.

预期读法： Then Juli started up with the goo-goo eyes again, and I was back to square one. Now, in sixth grade things changed, though whether they improved is hard to say. I don't remember Juli actually chasing me in the sixth grade. But I do remember her sniffing me. Yes, my friend, I said sniffing.

### C000005_088 · 完整片段 · narrator

[试听](audio/C000005_088.wav)

原文： And you can blame that on our teacher, Mr. Mertins. He stuck Juli to me like glue. Mr. Mertins has got some kind of doctorate in seating arrangements or something, because he analyzed and scrutinized and practically baptized the seats we had to sit in.

预期读法： And you can blame that on our teacher, Mr. Mertins. He stuck Juli to me like glue. Mr. Mertins has got some kind of doctorate in seating arrangements or something, because he analyzed and scrutinized and practically baptized the seats we had to sit in.

### C000005_089 · 完整片段 · narrator

[试听](audio/C000005_089.wav)

原文： And of course he decided to seat Juli right next to me. Juli Baker is the kind of annoying person who makes a point of letting you know she's smart. Her hand is the first one up; her answers are usually complete dissertations;

预期读法： And of course he decided to seat Juli right next to me. Juli Baker is the kind of annoying person who makes a point of letting you know she's smart. Her hand is the first one up; her answers are usually complete dissertations;

### C000005_090 · 完整片段 · narrator

[试听](audio/C000005_090.wav)

原文： her projects are always turned in early and used as weapons against the rest of the class. Teachers always have to hold her project up and say, “This is what I'm looking for, class.

预期读法： her projects are always turned in early and used as weapons against the rest of the class. Teachers always have to hold her project up and say, “This is what I'm looking for, class.

### C000005_091 · 完整片段 · narrator

[试听](audio/C000005_091.wav)

原文： This is an example of A-plus work.” Add all the extra credit she does to an already perfect score, and I swear she's never gotten less than 120 percent in any subject. But after Mr. Mertins stuck Juli right next to me, her annoying knowledge of all subjects far and wide came in handy.

预期读法： This is an example of A-plus work.” Add all the extra credit she does to an already perfect score, and I swear she's never gotten less than 120 percent in any subject. But after Mr. Mertins stuck Juli right next to me, her annoying knowledge of all subjects far and wide came in handy.

### C000005_092 · 完整片段 · narrator

[试听](audio/C000005_092.wav)

原文： See, suddenly Juli's perfect answers, written in perfect cursive, were right across the aisle, just an eye-shot away. You wouldn't believe the number of answers I snagged from her. I started getting A's and B's on everything! It was great! But then Mr. Mertins pulled the shift.

预期读法： See, suddenly Juli's perfect answers, written in perfect cursive, were right across the aisle, just an eye-shot away. You wouldn't believe the number of answers I snagged from her. I started getting A's and B's on everything! It was great! But then Mr. Mertins pulled the shift.

### C000005_093 · 完整片段 · narrator

[试听](audio/C000005_093.wav)

原文： He had some new idea for “optimizing positional latitude and longitude,” and when the dust finally settled, I was sitting right in front of Juli Baker. This is where the sniffing comes in. That maniac started leaning forward and sniffing my hair.

预期读法： He had some new idea for “optimizing positional latitude and longitude,” and when the dust finally settled, I was sitting right in front of Juli Baker. This is where the sniffing comes in. That maniac started leaning forward and sniffing my hair.

### C000005_094 · 完整片段 · narrator

[试听](audio/C000005_094.wav)

原文： She'd edge her nose practically up to my scalp and sniff-sniff-sniff. I tried elbowing and back-kicking. I tried scooting my chair way forward or putting my backpack between me and the seat. Nothing helped. She'd just scoot up, too, or lean over a little farther and sniff-sniff-sniff.

预期读法： She'd edge her nose practically up to my scalp and sniff-sniff-sniff. I tried elbowing and back-kicking. I tried scooting my chair way forward or putting my backpack between me and the seat. Nothing helped. She'd just scoot up, too, or lean over a little farther and sniff-sniff-sniff.

### C000005_095 · 完整片段 · narrator

[试听](audio/C000005_095.wav)

原文： I finally asked Mr. Mertins to move me, but he wouldn't do it. Something about not wanting to disturb the delicate balance of educational energies. Whatever. I was stuck with her sniffing. And since I couldn't see her perfectly penned answers anymore, my grades took a dive. Especially in spelling.

预期读法： I finally asked Mr. Mertins to move me, but he wouldn't do it. Something about not wanting to disturb the delicate balance of educational energies. Whatever. I was stuck with her sniffing. And since I couldn't see her perfectly penned answers anymore, my grades took a dive. Especially in spelling.

### C000005_096 · 完整片段 · narrator

[试听](audio/C000005_096.wav)

原文： Then one time, during a test, Juli's in the middle of sniffing my hair when she notices that I've blown a spelling word. A lot of words. Suddenly the sniffing stops and the whispering starts. At first I couldn't believe it. Juli Baker cheating?

预期读法： Then one time, during a test, Juli's in the middle of sniffing my hair when she notices that I've blown a spelling word. A lot of words. Suddenly the sniffing stops and the whispering starts. At first I couldn't believe it. Juli Baker cheating?

### C000005_097 · 完整片段 · narrator

[试听](audio/C000005_097.wav)

原文： But sure enough, she was spelling words for me, right in my ear. Juli'd always been sly about sniffing, which really bugged me because no one ever noticed her doing it, but she was just as sly about giving me answers, which was okay by me.

预期读法： But sure enough, she was spelling words for me, right in my ear. Juli'd always been sly about sniffing, which really bugged me because no one ever noticed her doing it, but she was just as sly about giving me answers, which was okay by me.

### C000005_098 · 完整片段 · narrator

[试听](audio/C000005_098.wav)

原文： The bad thing about it was that I started counting on her spelling in my ear. I mean, why study when you don't have to, right? But after a while, taking all those answers made me feel sort of indebted to her. How can you tell someone to bug off or quit sniffing you when you owe them?

预期读法： The bad thing about it was that I started counting on her spelling in my ear. I mean, why study when you don't have to, right? But after a while, taking all those answers made me feel sort of indebted to her. How can you tell someone to bug off or quit sniffing you when you owe them?

### C000005_099 · 完整片段 · narrator

[试听](audio/C000005_099.wav)

原文： It's, you know, wrong. So I spent the sixth grade somewhere between uncomfortable and unhappy, but I kept thinking that next year, next year, things would be different. We'd be in junior high — a big school — in different classes.

预期读法： It's, you know, wrong. So I spent the sixth grade somewhere between uncomfortable and unhappy, but I kept thinking that next year, next year, things would be different. We'd be in junior high — a big school — in different classes.

### C000005_100 · 完整片段 · narrator

[试听](audio/C000005_100.wav)

原文： It would be a world with too many people to worry about ever seeing Juli Baker again. It was finally, finally going to be over.

预期读法： It would be a world with too many people to worry about ever seeing Juli Baker again. It was finally, finally going to be over.

### B000005_001 · 同一角色

[接缝试听](audio/B000005_001.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：Diving Under All I've ever wanted is for Juli Baker to leave me alone. For her to back off — you know, just give me some space. It all started the summer before second grade when our moving van pulled into her neighborhood. ｜  And since we're now about done with the eighth grade, that, my friend, makes more than half a decade of strategic avoidance and social discomfort. She didn't just barge into my life. She barged and shoved and wedged her way into my life.

预期读法：Diving Under All I've ever wanted is for Juli Baker to leave me alone. For her to back off — you know, just give me some space. It all started the summer before second grade when our moving van pulled into her neighborhood. ｜  And since we're now about done with the eighth grade, that, my friend, makes more than half a decade of strategic avoidance and social discomfort. She didn't just barge into my life. She barged and shoved and wedged her way into my life.

### B000005_002 · 同一角色

[接缝试听](audio/B000005_002.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： And since we're now about done with the eighth grade, that, my friend, makes more than half a decade of strategic avoidance and social discomfort. She didn't just barge into my life. She barged and shoved and wedged her way into my life. ｜  Did we invite her to get into our moving van and start climbing all over boxes? No! But that's exactly what she did, taking over and showing off like only Juli Baker can. My dad tried to stop her. 

预期读法： And since we're now about done with the eighth grade, that, my friend, makes more than half a decade of strategic avoidance and social discomfort. She didn't just barge into my life. She barged and shoved and wedged her way into my life. ｜  Did we invite her to get into our moving van and start climbing all over boxes? No! But that's exactly what she did, taking over and showing off like only Juli Baker can. My dad tried to stop her. 

### B000005_003 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_003.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Did we invite her to get into our moving van and start climbing all over boxes? No! But that's exactly what she did, taking over and showing off like only Juli Baker can. My dad tried to stop her.  ｜ “Hey!”

预期读法： Did we invite her to get into our moving van and start climbing all over boxes? No! But that's exactly what she did, taking over and showing off like only Juli Baker can. My dad tried to stop her.  ｜ “Hey!”

### B000005_004 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_004.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Hey!” ｜  he says as she's catapulting herself on board. 

预期读法：“Hey!” ｜  he says as she's catapulting herself on board. 

### B000005_005 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_005.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： he says as she's catapulting herself on board.  ｜ “What are you doing? You're getting mud everywhere!”

预期读法： he says as she's catapulting herself on board.  ｜ “What are you doing? You're getting mud everywhere!”

### B000005_006 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_006.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“What are you doing? You're getting mud everywhere!” ｜  So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

预期读法：“What are you doing? You're getting mud everywhere!” ｜  So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet. 

### B000005_007 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_007.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet.  ｜ “Don't you want some help?”

预期读法： So true, too. Her shoes were, like, caked with the stuff. She didn't hop out, though. Instead, she planted her rear end on the floor and started pushing a big box with her feet.  ｜ “Don't you want some help?”

### B000005_008 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_008.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Don't you want some help?” ｜  She glanced my way. 

预期读法：“Don't you want some help?” ｜  She glanced my way. 

### B000005_009 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_009.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： She glanced my way.  ｜ “It sure looks like you need it.”

预期读法： She glanced my way.  ｜ “It sure looks like you need it.”

### B000005_010 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_010.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“It sure looks like you need it.” ｜  I didn't like the implication. And even though my dad had been tossing me the same sort of look all week, I could tell — he didn't like this girl either. 

预期读法：“It sure looks like you need it.” ｜  I didn't like the implication. And even though my dad had been tossing me the same sort of look all week, I could tell — he didn't like this girl either. 

### B000005_011 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_011.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I didn't like the implication. And even though my dad had been tossing me the same sort of look all week, I could tell — he didn't like this girl either.  ｜ “Hey! Don't do that,”

预期读法： I didn't like the implication. And even though my dad had been tossing me the same sort of look all week, I could tell — he didn't like this girl either.  ｜ “Hey! Don't do that,”

### B000005_012 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_012.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Hey! Don't do that,” ｜  he warned her. 

预期读法：“Hey! Don't do that,” ｜  he warned her. 

### B000005_013 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_013.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： he warned her.  ｜ “There are some really valuable things in that box.”

预期读法： he warned her.  ｜ “There are some really valuable things in that box.”

### B000005_014 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_014.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“There are some really valuable things in that box.” ｜ “Oh. Well, how about this one?”

预期读法：“There are some really valuable things in that box.” ｜ “Oh. Well, how about this one?”

### B000005_015 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_015.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Oh. Well, how about this one?” ｜  She scoots over to a box labeled LENOX and looks my way again. 

预期读法：“Oh. Well, how about this one?” ｜  She scoots over to a box labeled LENOX and looks my way again. 

### B000005_016 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_016.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： She scoots over to a box labeled LENOX and looks my way again.  ｜ “We should push it together!”

预期读法： She scoots over to a box labeled LENOX and looks my way again.  ｜ “We should push it together!”

### B000005_017 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_017.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“We should push it together!” ｜ “No, no, no!”

预期读法：“We should push it together!” ｜ “No, no, no!”

### B000005_018 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_018.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“No, no, no!” ｜  my dad says, then pulls her up by the arm. 

预期读法：“No, no, no!” ｜  my dad says, then pulls her up by the arm. 

### B000005_019 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_019.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： my dad says, then pulls her up by the arm.  ｜ “Why don't you run along home? Your mother's probably wondering where you are.”

预期读法： my dad says, then pulls her up by the arm.  ｜ “Why don't you run along home? Your mother's probably wondering where you are.”

### B000005_020 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_020.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Why don't you run along home? Your mother's probably wondering where you are.” ｜  This was the beginning of my soon-to-become-acute awareness that the girl cannot take a hint. Of any kind. Does she zip on home like a kid should when they've been invited to leave? No. She says, 

预期读法：“Why don't you run along home? Your mother's probably wondering where you are.” ｜  This was the beginning of my soon-to-become-acute awareness that the girl cannot take a hint. Of any kind. Does she zip on home like a kid should when they've been invited to leave? No. She says, 

### B000005_021 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_021.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： This was the beginning of my soon-to-become-acute awareness that the girl cannot take a hint. Of any kind. Does she zip on home like a kid should when they've been invited to leave? No. She says,  ｜ “Oh, my mom knows where I am. She said it was fine.”

预期读法： This was the beginning of my soon-to-become-acute awareness that the girl cannot take a hint. Of any kind. Does she zip on home like a kid should when they've been invited to leave? No. She says,  ｜ “Oh, my mom knows where I am. She said it was fine.”

### B000005_022 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_022.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Oh, my mom knows where I am. She said it was fine.” ｜  Then she points across the street and says, 

预期读法：“Oh, my mom knows where I am. She said it was fine.” ｜  Then she points across the street and says, 

### B000005_023 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_023.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Then she points across the street and says,  ｜ “We just live right over there.”

预期读法： Then she points across the street and says,  ｜ “We just live right over there.”

### B000005_024 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_024.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“We just live right over there.” ｜  My father looks to where she's pointing and mutters, 

预期读法：“We just live right over there.” ｜  My father looks to where she's pointing and mutters, 

### B000005_025 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_025.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： My father looks to where she's pointing and mutters,  ｜ “Oh boy.”

预期读法： My father looks to where she's pointing and mutters,  ｜ “Oh boy.”

### B000005_026 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_026.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Oh boy.” ｜  Then he looks at me and winks as he says, 

预期读法：“Oh boy.” ｜  Then he looks at me and winks as he says, 

### B000005_027 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_027.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Then he looks at me and winks as he says,  ｜ “Bryce, isn't it time for you to go inside and help your mother?”

预期读法： Then he looks at me and winks as he says,  ｜ “Bryce, isn't it time for you to go inside and help your mother?”

### B000005_028 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_028.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Bryce, isn't it time for you to go inside and help your mother?” ｜  I knew right off that this was a ditch play. And I didn't think about it until later, but ditch wasn't a play I'd run with my dad before. Face it, pulling a ditch is not something discussed with dads.

预期读法：“Bryce, isn't it time for you to go inside and help your mother?” ｜  I knew right off that this was a ditch play. And I didn't think about it until later, but ditch wasn't a play I'd run with my dad before. Face it, pulling a ditch is not something discussed with dads.

### B000005_029 · 同一角色

[接缝试听](audio/B000005_029.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I knew right off that this was a ditch play. And I didn't think about it until later, but ditch wasn't a play I'd run with my dad before. Face it, pulling a ditch is not something discussed with dads. ｜  It's like, against parental law to tell your kid it's okay to ditch someone, no matter how annoying or muddy they might be. But there he was, putting the play in motion, and man, he didn't have to wink twice. I smiled and said, “Sure thing!

预期读法： I knew right off that this was a ditch play. And I didn't think about it until later, but ditch wasn't a play I'd run with my dad before. Face it, pulling a ditch is not something discussed with dads. ｜  It's like, against parental law to tell your kid it's okay to ditch someone, no matter how annoying or muddy they might be. But there he was, putting the play in motion, and man, he didn't have to wink twice. I smiled and said, “Sure thing!

### B000005_030 · 同一角色

[接缝试听](audio/B000005_030.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： It's like, against parental law to tell your kid it's okay to ditch someone, no matter how annoying or muddy they might be. But there he was, putting the play in motion, and man, he didn't have to wink twice. I smiled and said, “Sure thing! ｜ ” then jumped off the liftgate and headed for my new front door. I heard her coming after me but I couldn't believe it. Maybe it just sounded like she was chasing me; maybe she was really going the other way.

预期读法： It's like, against parental law to tell your kid it's okay to ditch someone, no matter how annoying or muddy they might be. But there he was, putting the play in motion, and man, he didn't have to wink twice. I smiled and said, “Sure thing! ｜ ” then jumped off the liftgate and headed for my new front door. I heard her coming after me but I couldn't believe it. Maybe it just sounded like she was chasing me; maybe she was really going the other way.

### B000005_031 · 同一角色

[接缝试听](audio/B000005_031.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：” then jumped off the liftgate and headed for my new front door. I heard her coming after me but I couldn't believe it. Maybe it just sounded like she was chasing me; maybe she was really going the other way. ｜  But before I got up the nerve to look, she blasted right past me, grabbing my arm and yanking me along. This was too much. I planted myself and was about to tell her to get lost when the weirdest thing happened.

预期读法：” then jumped off the liftgate and headed for my new front door. I heard her coming after me but I couldn't believe it. Maybe it just sounded like she was chasing me; maybe she was really going the other way. ｜  But before I got up the nerve to look, she blasted right past me, grabbing my arm and yanking me along. This was too much. I planted myself and was about to tell her to get lost when the weirdest thing happened.

### B000005_032 · 同一角色

[接缝试听](audio/B000005_032.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： But before I got up the nerve to look, she blasted right past me, grabbing my arm and yanking me along. This was too much. I planted myself and was about to tell her to get lost when the weirdest thing happened. ｜  I was making this big windmill motion to break away from her, but somehow on the downswing my hand wound up tangling into hers. I couldn't believe it. There I was, holding the mud monkey's hand! I tried to shake her off, but she just clamped on tight and yanked me along, saying, 

预期读法： But before I got up the nerve to look, she blasted right past me, grabbing my arm and yanking me along. This was too much. I planted myself and was about to tell her to get lost when the weirdest thing happened. ｜  I was making this big windmill motion to break away from her, but somehow on the downswing my hand wound up tangling into hers. I couldn't believe it. There I was, holding the mud monkey's hand! I tried to shake her off, but she just clamped on tight and yanked me along, saying, 

### B000005_033 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_033.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I was making this big windmill motion to break away from her, but somehow on the downswing my hand wound up tangling into hers. I couldn't believe it. There I was, holding the mud monkey's hand! I tried to shake her off, but she just clamped on tight and yanked me along, saying,  ｜ “C'mon!”

预期读法： I was making this big windmill motion to break away from her, but somehow on the downswing my hand wound up tangling into hers. I couldn't believe it. There I was, holding the mud monkey's hand! I tried to shake her off, but she just clamped on tight and yanked me along, saying,  ｜ “C'mon!”

### B000005_034 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_034.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“C'mon!” ｜  My mom came out of the house and immediately got the world's sappiest look on her face. 

预期读法：“C'mon!” ｜  My mom came out of the house and immediately got the world's sappiest look on her face. 

### B000005_035 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_035.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： My mom came out of the house and immediately got the world's sappiest look on her face.  ｜ “Well, hello,”

预期读法： My mom came out of the house and immediately got the world's sappiest look on her face.  ｜ “Well, hello,”

### B000005_036 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_036.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Well, hello,” ｜  she says to Juli. 

预期读法：“Well, hello,” ｜  she says to Juli. 

### B000005_037 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_037.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： she says to Juli.  ｜ “Hi!”

预期读法： she says to Juli.  ｜ “Hi!”

### B000005_038 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_038.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Hi!” ｜  I'm still trying to pull free, but the girl's got me in a death grip. My mom's grinning, looking at our hands and my fiery red face. 

预期读法：“Hi!” ｜  I'm still trying to pull free, but the girl's got me in a death grip. My mom's grinning, looking at our hands and my fiery red face. 

### B000005_039 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_039.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I'm still trying to pull free, but the girl's got me in a death grip. My mom's grinning, looking at our hands and my fiery red face.  ｜ “And what's your name, honey?”

预期读法： I'm still trying to pull free, but the girl's got me in a death grip. My mom's grinning, looking at our hands and my fiery red face.  ｜ “And what's your name, honey?”

### B000005_040 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_040.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“And what's your name, honey?” ｜ “Julianna Baker. I live right over there,”

预期读法：“And what's your name, honey?” ｜ “Julianna Baker. I live right over there,”

### B000005_041 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_041.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Julianna Baker. I live right over there,” ｜  she says, pointing with her unoccupied hand. 

预期读法：“Julianna Baker. I live right over there,” ｜  she says, pointing with her unoccupied hand. 

### B000005_042 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_042.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： she says, pointing with her unoccupied hand.  ｜ “Well, I see you've met my son,”

预期读法： she says, pointing with her unoccupied hand.  ｜ “Well, I see you've met my son,”

### B000005_043 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_043.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Well, I see you've met my son,” ｜  she says, still grinning away. 

预期读法：“Well, I see you've met my son,” ｜  she says, still grinning away. 

### B000005_044 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_044.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： she says, still grinning away.  ｜ “Uh-huh!”

预期读法： she says, still grinning away.  ｜ “Uh-huh!”

### B000005_045 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_045.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Uh-huh!” ｜  Finally I break free and do the only manly thing available when you're seven years old — I dive behind my mother. Mom puts her arm around me and says, 

预期读法：“Uh-huh!” ｜  Finally I break free and do the only manly thing available when you're seven years old — I dive behind my mother. Mom puts her arm around me and says, 

### B000005_046 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_046.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Finally I break free and do the only manly thing available when you're seven years old — I dive behind my mother. Mom puts her arm around me and says,  ｜ “Bryce, honey, why don't you show Julianna around the house?”

预期读法： Finally I break free and do the only manly thing available when you're seven years old — I dive behind my mother. Mom puts her arm around me and says,  ｜ “Bryce, honey, why don't you show Julianna around the house?”

### B000005_047 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_047.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Bryce, honey, why don't you show Julianna around the house?” ｜  I flash her help and warning signals with every part of my body, but she's not receiving. Then she shakes me off and says, 

预期读法：“Bryce, honey, why don't you show Julianna around the house?” ｜  I flash her help and warning signals with every part of my body, but she's not receiving. Then she shakes me off and says, 

### B000005_048 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_048.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I flash her help and warning signals with every part of my body, but she's not receiving. Then she shakes me off and says,  ｜ “Go on.”

预期读法： I flash her help and warning signals with every part of my body, but she's not receiving. Then she shakes me off and says,  ｜ “Go on.”

### B000005_049 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_049.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Go on.” ｜  Juli would've tramped right in if my mother hadn't noticed her shoes and told her to take them off. And after those were off, my mom told her that her dirty socks had to go, too. Juli wasn't embarrassed. Not a bit. She just peeled them off and left them in a crusty heap on our porch.

预期读法：“Go on.” ｜  Juli would've tramped right in if my mother hadn't noticed her shoes and told her to take them off. And after those were off, my mom told her that her dirty socks had to go, too. Juli wasn't embarrassed. Not a bit. She just peeled them off and left them in a crusty heap on our porch.

### B000005_050 · 同一角色

[接缝试听](audio/B000005_050.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Juli would've tramped right in if my mother hadn't noticed her shoes and told her to take them off. And after those were off, my mom told her that her dirty socks had to go, too. Juli wasn't embarrassed. Not a bit. She just peeled them off and left them in a crusty heap on our porch. ｜  I didn't exactly give her a tour. I locked myself in the bathroom instead. And after about ten minutes of yelling back at her that no, I wasn't coming out anytime soon, things got quiet out in the hall. Another ten minutes went by before I got the nerve to peek out the door. No Juli.

预期读法： Juli would've tramped right in if my mother hadn't noticed her shoes and told her to take them off. And after those were off, my mom told her that her dirty socks had to go, too. Juli wasn't embarrassed. Not a bit. She just peeled them off and left them in a crusty heap on our porch. ｜  I didn't exactly give her a tour. I locked myself in the bathroom instead. And after about ten minutes of yelling back at her that no, I wasn't coming out anytime soon, things got quiet out in the hall. Another ten minutes went by before I got the nerve to peek out the door. No Juli.

### B000005_051 · 同一角色

[接缝试听](audio/B000005_051.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I didn't exactly give her a tour. I locked myself in the bathroom instead. And after about ten minutes of yelling back at her that no, I wasn't coming out anytime soon, things got quiet out in the hall. Another ten minutes went by before I got the nerve to peek out the door. No Juli. ｜  I snuck out and looked around, and yes! She was gone. Not a very sophisticated ditch, but hey, I was only seven. My troubles were far from over, though. Every day she came back, over and over again. 

预期读法： I didn't exactly give her a tour. I locked myself in the bathroom instead. And after about ten minutes of yelling back at her that no, I wasn't coming out anytime soon, things got quiet out in the hall. Another ten minutes went by before I got the nerve to peek out the door. No Juli. ｜  I snuck out and looked around, and yes! She was gone. Not a very sophisticated ditch, but hey, I was only seven. My troubles were far from over, though. Every day she came back, over and over again. 

### B000005_052 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_052.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I snuck out and looked around, and yes! She was gone. Not a very sophisticated ditch, but hey, I was only seven. My troubles were far from over, though. Every day she came back, over and over again.  ｜ “Can Bryce play?”

预期读法： I snuck out and looked around, and yes! She was gone. Not a very sophisticated ditch, but hey, I was only seven. My troubles were far from over, though. Every day she came back, over and over again.  ｜ “Can Bryce play?”

### B000005_053 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_053.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Can Bryce play?” ｜  I could hear her asking from my hiding place behind the couch. 

预期读法：“Can Bryce play?” ｜  I could hear her asking from my hiding place behind the couch. 

### B000005_054 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_054.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I could hear her asking from my hiding place behind the couch.  ｜ “Is he ready yet?”

预期读法： I could hear her asking from my hiding place behind the couch.  ｜ “Is he ready yet?”

### B000005_055 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_055.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Is he ready yet?” ｜  One time she even cut across the yard and looked through my window. I spotted her in the nick of time and dove under my bed, but man, that right there tells you something about Juli Baker. She's got no concept of personal space. No respect for privacy.

预期读法：“Is he ready yet?” ｜  One time she even cut across the yard and looked through my window. I spotted her in the nick of time and dove under my bed, but man, that right there tells you something about Juli Baker. She's got no concept of personal space. No respect for privacy.

### B000005_056 · 同一角色

[接缝试听](audio/B000005_056.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： One time she even cut across the yard and looked through my window. I spotted her in the nick of time and dove under my bed, but man, that right there tells you something about Juli Baker. She's got no concept of personal space. No respect for privacy. ｜  The world is her playground, and watch out below — Juli's on the slide! Lucky for me, my dad was willing to run block. And he did it over and over again. He told her I was busy or sleeping or just plain gone. He was a lifesaver. My sister, on the other hand, tried to sabotage me any chance she got.

预期读法： One time she even cut across the yard and looked through my window. I spotted her in the nick of time and dove under my bed, but man, that right there tells you something about Juli Baker. She's got no concept of personal space. No respect for privacy. ｜  The world is her playground, and watch out below — Juli's on the slide! Lucky for me, my dad was willing to run block. And he did it over and over again. He told her I was busy or sleeping or just plain gone. He was a lifesaver. My sister, on the other hand, tried to sabotage me any chance she got.

### B000005_057 · 同一角色

[接缝试听](audio/B000005_057.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： The world is her playground, and watch out below — Juli's on the slide! Lucky for me, my dad was willing to run block. And he did it over and over again. He told her I was busy or sleeping or just plain gone. He was a lifesaver. My sister, on the other hand, tried to sabotage me any chance she got. ｜  Lynetta's like that. She's four years older than me, and buddy, I've learned from watching her how not to run your life. She's got ANTAGONIZE written all over her. Just look at her — not cross-eyed or with your tongue sticking out or anything — just look at her and you've started an argument.

预期读法： The world is her playground, and watch out below — Juli's on the slide! Lucky for me, my dad was willing to run block. And he did it over and over again. He told her I was busy or sleeping or just plain gone. He was a lifesaver. My sister, on the other hand, tried to sabotage me any chance she got. ｜  Lynetta's like that. She's four years older than me, and buddy, I've learned from watching her how not to run your life. She's got ANTAGONIZE written all over her. Just look at her — not cross-eyed or with your tongue sticking out or anything — just look at her and you've started an argument.

### B000005_058 · 同一角色

[接缝试听](audio/B000005_058.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Lynetta's like that. She's four years older than me, and buddy, I've learned from watching her how not to run your life. She's got ANTAGONIZE written all over her. Just look at her — not cross-eyed or with your tongue sticking out or anything — just look at her and you've started an argument. ｜  I used to knock-down-drag-out with her, but it's just not worth it. Girls don't fight fair. They pull your hair and gouge you and pinch you; then they run off gasping to mommy when you try and defend yourself with a fist. Then you get locked into time-out, and for what?

预期读法： Lynetta's like that. She's four years older than me, and buddy, I've learned from watching her how not to run your life. She's got ANTAGONIZE written all over her. Just look at her — not cross-eyed or with your tongue sticking out or anything — just look at her and you've started an argument. ｜  I used to knock-down-drag-out with her, but it's just not worth it. Girls don't fight fair. They pull your hair and gouge you and pinch you; then they run off gasping to mommy when you try and defend yourself with a fist. Then you get locked into time-out, and for what?

### B000005_059 · 同一角色

[接缝试听](audio/B000005_059.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I used to knock-down-drag-out with her, but it's just not worth it. Girls don't fight fair. They pull your hair and gouge you and pinch you; then they run off gasping to mommy when you try and defend yourself with a fist. Then you get locked into time-out, and for what? ｜  No, my friend, the secret is, don't snap at the bait. Let it dangle. Swim around it. Laugh it off. After a while they'll give up and try to lure someone else. At least that's the way it is with Lynetta.

预期读法： I used to knock-down-drag-out with her, but it's just not worth it. Girls don't fight fair. They pull your hair and gouge you and pinch you; then they run off gasping to mommy when you try and defend yourself with a fist. Then you get locked into time-out, and for what? ｜  No, my friend, the secret is, don't snap at the bait. Let it dangle. Swim around it. Laugh it off. After a while they'll give up and try to lure someone else. At least that's the way it is with Lynetta.

### B000005_060 · 同一角色

[接缝试听](audio/B000005_060.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： No, my friend, the secret is, don't snap at the bait. Let it dangle. Swim around it. Laugh it off. After a while they'll give up and try to lure someone else. At least that's the way it is with Lynetta. ｜  And the bonus of having her as a pain-in-the-rear sister was figuring out that this method works on everyone. Teachers, jerks at school, even Mom and Dad. Seriously. There's no winning arguments with your parents, so why get all pumped up over them?

预期读法： No, my friend, the secret is, don't snap at the bait. Let it dangle. Swim around it. Laugh it off. After a while they'll give up and try to lure someone else. At least that's the way it is with Lynetta. ｜  And the bonus of having her as a pain-in-the-rear sister was figuring out that this method works on everyone. Teachers, jerks at school, even Mom and Dad. Seriously. There's no winning arguments with your parents, so why get all pumped up over them?

### B000005_061 · 同一角色

[接缝试听](audio/B000005_061.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： And the bonus of having her as a pain-in-the-rear sister was figuring out that this method works on everyone. Teachers, jerks at school, even Mom and Dad. Seriously. There's no winning arguments with your parents, so why get all pumped up over them? ｜  It is way better to dive down and get out of the way than it is to get clobbered by some parental tidal wave. The funny thing is, Lynetta's still clueless when it comes to dealing with Mom and Dad.

预期读法： And the bonus of having her as a pain-in-the-rear sister was figuring out that this method works on everyone. Teachers, jerks at school, even Mom and Dad. Seriously. There's no winning arguments with your parents, so why get all pumped up over them? ｜  It is way better to dive down and get out of the way than it is to get clobbered by some parental tidal wave. The funny thing is, Lynetta's still clueless when it comes to dealing with Mom and Dad.

### B000005_062 · 同一角色

[接缝试听](audio/B000005_062.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： It is way better to dive down and get out of the way than it is to get clobbered by some parental tidal wave. The funny thing is, Lynetta's still clueless when it comes to dealing with Mom and Dad. ｜  She goes straight into thrash mode and is too busy drowning in the argument to take a deep breath and dive for calmer water. And she thinks I'm stupid. Anyway, true to form, Lynetta tried to bait me with Juli those first few days.

预期读法： It is way better to dive down and get out of the way than it is to get clobbered by some parental tidal wave. The funny thing is, Lynetta's still clueless when it comes to dealing with Mom and Dad. ｜  She goes straight into thrash mode and is too busy drowning in the argument to take a deep breath and dive for calmer water. And she thinks I'm stupid. Anyway, true to form, Lynetta tried to bait me with Juli those first few days.

### B000005_063 · 同一角色

[接缝试听](audio/B000005_063.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： She goes straight into thrash mode and is too busy drowning in the argument to take a deep breath and dive for calmer water. And she thinks I'm stupid. Anyway, true to form, Lynetta tried to bait me with Juli those first few days. ｜  She even snuck her past Dad once and marched her all around the house, hunting me down. I wedged myself up on the top shelf of my closet, and lucky for me, neither of them looked up. A few minutes later I heard Dad yell at Juli to get off the antique furniture, and once again, she got booted.

预期读法： She goes straight into thrash mode and is too busy drowning in the argument to take a deep breath and dive for calmer water. And she thinks I'm stupid. Anyway, true to form, Lynetta tried to bait me with Juli those first few days. ｜  She even snuck her past Dad once and marched her all around the house, hunting me down. I wedged myself up on the top shelf of my closet, and lucky for me, neither of them looked up. A few minutes later I heard Dad yell at Juli to get off the antique furniture, and once again, she got booted.

### B000005_064 · 同一角色

[接缝试听](audio/B000005_064.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： She even snuck her past Dad once and marched her all around the house, hunting me down. I wedged myself up on the top shelf of my closet, and lucky for me, neither of them looked up. A few minutes later I heard Dad yell at Juli to get off the antique furniture, and once again, she got booted. ｜  I don't think I went outside that whole first week. I helped unpack stuff and watched TV and just kind of hung around while my mom and dad arranged and rearranged the furniture, debating whether Empire settees and French Rococo tables should even be put in the same room.

预期读法： She even snuck her past Dad once and marched her all around the house, hunting me down. I wedged myself up on the top shelf of my closet, and lucky for me, neither of them looked up. A few minutes later I heard Dad yell at Juli to get off the antique furniture, and once again, she got booted. ｜  I don't think I went outside that whole first week. I helped unpack stuff and watched TV and just kind of hung around while my mom and dad arranged and rearranged the furniture, debating whether Empire settees and French Rococo tables should even be put in the same room.

### B000005_065 · 同一角色

[接缝试听](audio/B000005_065.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I don't think I went outside that whole first week. I helped unpack stuff and watched TV and just kind of hung around while my mom and dad arranged and rearranged the furniture, debating whether Empire settees and French Rococo tables should even be put in the same room. ｜  So believe me, I was dying to go outside. But every time I checked through the window, I could see Juli showing off in her yard. She'd be heading a soccer ball or doing high kicks with it or dribbling it up and down their driveway.

预期读法： I don't think I went outside that whole first week. I helped unpack stuff and watched TV and just kind of hung around while my mom and dad arranged and rearranged the furniture, debating whether Empire settees and French Rococo tables should even be put in the same room. ｜  So believe me, I was dying to go outside. But every time I checked through the window, I could see Juli showing off in her yard. She'd be heading a soccer ball or doing high kicks with it or dribbling it up and down their driveway.

### B000005_066 · 同一角色

[接缝试听](audio/B000005_066.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： So believe me, I was dying to go outside. But every time I checked through the window, I could see Juli showing off in her yard. She'd be heading a soccer ball or doing high kicks with it or dribbling it up and down their driveway. ｜  And when she wasn't busy showing off, she'd just sit on the curb with the ball between her feet, staring at our house. My mom didn't understand why it was so awful that “that cute little girl” had held my hand. She thought I should make friends with her. 

预期读法： So believe me, I was dying to go outside. But every time I checked through the window, I could see Juli showing off in her yard. She'd be heading a soccer ball or doing high kicks with it or dribbling it up and down their driveway. ｜  And when she wasn't busy showing off, she'd just sit on the curb with the ball between her feet, staring at our house. My mom didn't understand why it was so awful that “that cute little girl” had held my hand. She thought I should make friends with her. 

### B000005_067 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_067.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： And when she wasn't busy showing off, she'd just sit on the curb with the ball between her feet, staring at our house. My mom didn't understand why it was so awful that “that cute little girl” had held my hand. She thought I should make friends with her.  ｜ “I thought you liked soccer, honey. Why don't you go out there and kick the ball around?”

预期读法： And when she wasn't busy showing off, she'd just sit on the curb with the ball between her feet, staring at our house. My mom didn't understand why it was so awful that “that cute little girl” had held my hand. She thought I should make friends with her.  ｜ “I thought you liked soccer, honey. Why don't you go out there and kick the ball around?”

### B000005_068 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_068.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“I thought you liked soccer, honey. Why don't you go out there and kick the ball around?” ｜  Because I didn't want to be kicked around, that's why. And although I couldn't say it like that at the time, I still had enough sense at age seven and a half to know that Juli Baker was dangerous. Unavoidably dangerous, as it turns out.

预期读法：“I thought you liked soccer, honey. Why don't you go out there and kick the ball around?” ｜  Because I didn't want to be kicked around, that's why. And although I couldn't say it like that at the time, I still had enough sense at age seven and a half to know that Juli Baker was dangerous. Unavoidably dangerous, as it turns out.

### B000005_069 · 同一角色

[接缝试听](audio/B000005_069.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Because I didn't want to be kicked around, that's why. And although I couldn't say it like that at the time, I still had enough sense at age seven and a half to know that Juli Baker was dangerous. Unavoidably dangerous, as it turns out. ｜  The minute I walked into Mrs. Yelson's second-grade classroom, I was dead meat. 

预期读法： Because I didn't want to be kicked around, that's why. And although I couldn't say it like that at the time, I still had enough sense at age seven and a half to know that Juli Baker was dangerous. Unavoidably dangerous, as it turns out. ｜  The minute I walked into Mrs. Yelson's second-grade classroom, I was dead meat. 

### B000005_070 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_070.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： The minute I walked into Mrs. Yelson's second-grade classroom, I was dead meat.  ｜ “Bryce!”

预期读法： The minute I walked into Mrs. Yelson's second-grade classroom, I was dead meat.  ｜ “Bryce!”

### B000005_071 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_071.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Bryce!” ｜  Juli squeals. 

预期读法：“Bryce!” ｜  Juli squeals. 

### B000005_072 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_072.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Juli squeals.  ｜ “You're here.”

预期读法： Juli squeals.  ｜ “You're here.”

### B000005_073 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_073.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“You're here.” ｜  Then she charges across the room and tackles me. Mrs. Yelson tried to explain this attack away as a “welcome hug,” but man, that was no hug. That was a front-line, take-'em-down tackle. And even though I shook her off, it was too late. I was branded for life. Everyone jeered, 

预期读法：“You're here.” ｜  Then she charges across the room and tackles me. Mrs. Yelson tried to explain this attack away as a “welcome hug,” but man, that was no hug. That was a front-line, take-'em-down tackle. And even though I shook her off, it was too late. I was branded for life. Everyone jeered, 

### B000005_074 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_074.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Then she charges across the room and tackles me. Mrs. Yelson tried to explain this attack away as a “welcome hug,” but man, that was no hug. That was a front-line, take-'em-down tackle. And even though I shook her off, it was too late. I was branded for life. Everyone jeered,  ｜ “Where's your girl friend, Bryce?”

预期读法： Then she charges across the room and tackles me. Mrs. Yelson tried to explain this attack away as a “welcome hug,” but man, that was no hug. That was a front-line, take-'em-down tackle. And even though I shook her off, it was too late. I was branded for life. Everyone jeered,  ｜ “Where's your girl friend, Bryce?”

### B000005_075 · 同一角色

[接缝试听](audio/B000005_075.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Where's your girl friend, Bryce?” ｜ “Are you married yet, Bryce?”

预期读法：“Where's your girl friend, Bryce?” ｜ “Are you married yet, Bryce?”

### B000005_076 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_076.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Are you married yet, Bryce?” ｜  And then when she chased me around at recess and tried to lay kisses on me, the whole school started singing, 

预期读法：“Are you married yet, Bryce?” ｜  And then when she chased me around at recess and tried to lay kisses on me, the whole school started singing, 

### B000005_077 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_077.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： And then when she chased me around at recess and tried to lay kisses on me, the whole school started singing,  ｜ “Bryce and Juli sitting in a tree, K-I-S-S-I-N-G…”

预期读法： And then when she chased me around at recess and tried to lay kisses on me, the whole school started singing,  ｜ “Bryce and Juli sitting in a tree, K-I-S-S-I-N-G…”

### B000005_078 · 角色切换，正常换声音不算漂移

[接缝试听](audio/B000005_078.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文：“Bryce and Juli sitting in a tree, K-I-S-S-I-N-G…” ｜  My first year in town was a disaster. Third grade wasn't much better. She was still hot on my trail every time I turned around. Same with fourth. But then in fifth grade I took action. It started out slow — one of those Nah-that's-not-right ideas you get and forget.

预期读法：“Bryce and Juli sitting in a tree, K-I-S-S-I-N-G…” ｜  My first year in town was a disaster. Third grade wasn't much better. She was still hot on my trail every time I turned around. Same with fourth. But then in fifth grade I took action. It started out slow — one of those Nah-that's-not-right ideas you get and forget.

### B000005_079 · 同一角色

[接缝试听](audio/B000005_079.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： My first year in town was a disaster. Third grade wasn't much better. She was still hot on my trail every time I turned around. Same with fourth. But then in fifth grade I took action. It started out slow — one of those Nah-that's-not-right ideas you get and forget. ｜  But the more I played with the idea, the more I thought, What better way to ward Juli off? What better way to say to her, “Juli, you are not my type”? And so, my friend, I hatched the plan. I asked Shelly Stalls out.

预期读法： My first year in town was a disaster. Third grade wasn't much better. She was still hot on my trail every time I turned around. Same with fourth. But then in fifth grade I took action. It started out slow — one of those Nah-that's-not-right ideas you get and forget. ｜  But the more I played with the idea, the more I thought, What better way to ward Juli off? What better way to say to her, “Juli, you are not my type”? And so, my friend, I hatched the plan. I asked Shelly Stalls out.

### B000005_080 · 同一角色

[接缝试听](audio/B000005_080.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： But the more I played with the idea, the more I thought, What better way to ward Juli off? What better way to say to her, “Juli, you are not my type”? And so, my friend, I hatched the plan. I asked Shelly Stalls out. ｜  To fully appreciate the brilliance of this, you have to understand that Juli hates Shelly Stalls. She always has, though it beats me why. Shelly's nice and she's friendly and she's got a lot of hair. What's not to like?

预期读法： But the more I played with the idea, the more I thought, What better way to ward Juli off? What better way to say to her, “Juli, you are not my type”? And so, my friend, I hatched the plan. I asked Shelly Stalls out. ｜  To fully appreciate the brilliance of this, you have to understand that Juli hates Shelly Stalls. She always has, though it beats me why. Shelly's nice and she's friendly and she's got a lot of hair. What's not to like?

### B000005_081 · 同一角色

[接缝试听](audio/B000005_081.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： To fully appreciate the brilliance of this, you have to understand that Juli hates Shelly Stalls. She always has, though it beats me why. Shelly's nice and she's friendly and she's got a lot of hair. What's not to like? ｜  But Juli hated her, and I was going to make this little gem of knowledge the solution to my problem. What I was thinking was that Shelly would eat lunch at our table and maybe walk around a little with me.

预期读法： To fully appreciate the brilliance of this, you have to understand that Juli hates Shelly Stalls. She always has, though it beats me why. Shelly's nice and she's friendly and she's got a lot of hair. What's not to like? ｜  But Juli hated her, and I was going to make this little gem of knowledge the solution to my problem. What I was thinking was that Shelly would eat lunch at our table and maybe walk around a little with me.

### B000005_082 · 同一角色

[接缝试听](audio/B000005_082.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： But Juli hated her, and I was going to make this little gem of knowledge the solution to my problem. What I was thinking was that Shelly would eat lunch at our table and maybe walk around a little with me. ｜  That way, anytime Juli was around, all I'd have to do was hang a little closer to Shelly and things would just naturally take care of themselves. What happened, though, is that Shelly took things way too seriously. She went around telling everybody — including Juli — that we were in love.

预期读法： But Juli hated her, and I was going to make this little gem of knowledge the solution to my problem. What I was thinking was that Shelly would eat lunch at our table and maybe walk around a little with me. ｜  That way, anytime Juli was around, all I'd have to do was hang a little closer to Shelly and things would just naturally take care of themselves. What happened, though, is that Shelly took things way too seriously. She went around telling everybody — including Juli — that we were in love.

### B000005_083 · 同一角色

[接缝试听](audio/B000005_083.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： That way, anytime Juli was around, all I'd have to do was hang a little closer to Shelly and things would just naturally take care of themselves. What happened, though, is that Shelly took things way too seriously. She went around telling everybody — including Juli — that we were in love. ｜  In no time Juli and Shelly got into some kind of catfight, and while Shelly was recovering from that, my supposed friend Garrett — who had been totally behind this plan — told her what I was up to.

预期读法： That way, anytime Juli was around, all I'd have to do was hang a little closer to Shelly and things would just naturally take care of themselves. What happened, though, is that Shelly took things way too seriously. She went around telling everybody — including Juli — that we were in love. ｜  In no time Juli and Shelly got into some kind of catfight, and while Shelly was recovering from that, my supposed friend Garrett — who had been totally behind this plan — told her what I was up to.

### B000005_084 · 同一角色

[接缝试听](audio/B000005_084.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： In no time Juli and Shelly got into some kind of catfight, and while Shelly was recovering from that, my supposed friend Garrett — who had been totally behind this plan — told her what I was up to. ｜  He's always denied it, but I've since learned that his code of honor is easily corrupted by weepy females. That afternoon the principal tried cross-examining me, but I wouldn't cop to anything. I just kept telling her that I was sorry and that I really didn't understand what had happened.

预期读法： In no time Juli and Shelly got into some kind of catfight, and while Shelly was recovering from that, my supposed friend Garrett — who had been totally behind this plan — told her what I was up to. ｜  He's always denied it, but I've since learned that his code of honor is easily corrupted by weepy females. That afternoon the principal tried cross-examining me, but I wouldn't cop to anything. I just kept telling her that I was sorry and that I really didn't understand what had happened.

### B000005_085 · 同一角色

[接缝试听](audio/B000005_085.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： He's always denied it, but I've since learned that his code of honor is easily corrupted by weepy females. That afternoon the principal tried cross-examining me, but I wouldn't cop to anything. I just kept telling her that I was sorry and that I really didn't understand what had happened. ｜  Finally she let me go. Shelly cried for days and followed me around school sniffling and making me feel like a real jerk, which was even worse than having Juli as a shadow. Everything blew over at the one-week mark, though, when Shelly officially dumped me and started going out with Kyle Larsen.

预期读法： He's always denied it, but I've since learned that his code of honor is easily corrupted by weepy females. That afternoon the principal tried cross-examining me, but I wouldn't cop to anything. I just kept telling her that I was sorry and that I really didn't understand what had happened. ｜  Finally she let me go. Shelly cried for days and followed me around school sniffling and making me feel like a real jerk, which was even worse than having Juli as a shadow. Everything blew over at the one-week mark, though, when Shelly officially dumped me and started going out with Kyle Larsen.

### B000005_086 · 同一角色

[接缝试听](audio/B000005_086.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Finally she let me go. Shelly cried for days and followed me around school sniffling and making me feel like a real jerk, which was even worse than having Juli as a shadow. Everything blew over at the one-week mark, though, when Shelly officially dumped me and started going out with Kyle Larsen. ｜  Then Juli started up with the goo-goo eyes again, and I was back to square one. Now, in sixth grade things changed, though whether they improved is hard to say. I don't remember Juli actually chasing me in the sixth grade. But I do remember her sniffing me. Yes, my friend, I said sniffing.

预期读法： Finally she let me go. Shelly cried for days and followed me around school sniffling and making me feel like a real jerk, which was even worse than having Juli as a shadow. Everything blew over at the one-week mark, though, when Shelly officially dumped me and started going out with Kyle Larsen. ｜  Then Juli started up with the goo-goo eyes again, and I was back to square one. Now, in sixth grade things changed, though whether they improved is hard to say. I don't remember Juli actually chasing me in the sixth grade. But I do remember her sniffing me. Yes, my friend, I said sniffing.

### B000005_087 · 同一角色

[接缝试听](audio/B000005_087.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Then Juli started up with the goo-goo eyes again, and I was back to square one. Now, in sixth grade things changed, though whether they improved is hard to say. I don't remember Juli actually chasing me in the sixth grade. But I do remember her sniffing me. Yes, my friend, I said sniffing. ｜  And you can blame that on our teacher, Mr. Mertins. He stuck Juli to me like glue. Mr. Mertins has got some kind of doctorate in seating arrangements or something, because he analyzed and scrutinized and practically baptized the seats we had to sit in.

预期读法： Then Juli started up with the goo-goo eyes again, and I was back to square one. Now, in sixth grade things changed, though whether they improved is hard to say. I don't remember Juli actually chasing me in the sixth grade. But I do remember her sniffing me. Yes, my friend, I said sniffing. ｜  And you can blame that on our teacher, Mr. Mertins. He stuck Juli to me like glue. Mr. Mertins has got some kind of doctorate in seating arrangements or something, because he analyzed and scrutinized and practically baptized the seats we had to sit in.

### B000005_088 · 同一角色

[接缝试听](audio/B000005_088.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： And you can blame that on our teacher, Mr. Mertins. He stuck Juli to me like glue. Mr. Mertins has got some kind of doctorate in seating arrangements or something, because he analyzed and scrutinized and practically baptized the seats we had to sit in. ｜  And of course he decided to seat Juli right next to me. Juli Baker is the kind of annoying person who makes a point of letting you know she's smart. Her hand is the first one up; her answers are usually complete dissertations;

预期读法： And you can blame that on our teacher, Mr. Mertins. He stuck Juli to me like glue. Mr. Mertins has got some kind of doctorate in seating arrangements or something, because he analyzed and scrutinized and practically baptized the seats we had to sit in. ｜  And of course he decided to seat Juli right next to me. Juli Baker is the kind of annoying person who makes a point of letting you know she's smart. Her hand is the first one up; her answers are usually complete dissertations;

### B000005_089 · 同一角色

[接缝试听](audio/B000005_089.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： And of course he decided to seat Juli right next to me. Juli Baker is the kind of annoying person who makes a point of letting you know she's smart. Her hand is the first one up; her answers are usually complete dissertations; ｜  her projects are always turned in early and used as weapons against the rest of the class. Teachers always have to hold her project up and say, “This is what I'm looking for, class.

预期读法： And of course he decided to seat Juli right next to me. Juli Baker is the kind of annoying person who makes a point of letting you know she's smart. Her hand is the first one up; her answers are usually complete dissertations; ｜  her projects are always turned in early and used as weapons against the rest of the class. Teachers always have to hold her project up and say, “This is what I'm looking for, class.

### B000005_090 · 同一角色

[接缝试听](audio/B000005_090.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： her projects are always turned in early and used as weapons against the rest of the class. Teachers always have to hold her project up and say, “This is what I'm looking for, class. ｜  This is an example of A-plus work.” Add all the extra credit she does to an already perfect score, and I swear she's never gotten less than 120 percent in any subject. But after Mr. Mertins stuck Juli right next to me, her annoying knowledge of all subjects far and wide came in handy.

预期读法： her projects are always turned in early and used as weapons against the rest of the class. Teachers always have to hold her project up and say, “This is what I'm looking for, class. ｜  This is an example of A-plus work.” Add all the extra credit she does to an already perfect score, and I swear she's never gotten less than 120 percent in any subject. But after Mr. Mertins stuck Juli right next to me, her annoying knowledge of all subjects far and wide came in handy.

### B000005_091 · 同一角色

[接缝试听](audio/B000005_091.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： This is an example of A-plus work.” Add all the extra credit she does to an already perfect score, and I swear she's never gotten less than 120 percent in any subject. But after Mr. Mertins stuck Juli right next to me, her annoying knowledge of all subjects far and wide came in handy. ｜  See, suddenly Juli's perfect answers, written in perfect cursive, were right across the aisle, just an eye-shot away. You wouldn't believe the number of answers I snagged from her. I started getting A's and B's on everything! It was great! But then Mr. Mertins pulled the shift.

预期读法： This is an example of A-plus work.” Add all the extra credit she does to an already perfect score, and I swear she's never gotten less than 120 percent in any subject. But after Mr. Mertins stuck Juli right next to me, her annoying knowledge of all subjects far and wide came in handy. ｜  See, suddenly Juli's perfect answers, written in perfect cursive, were right across the aisle, just an eye-shot away. You wouldn't believe the number of answers I snagged from her. I started getting A's and B's on everything! It was great! But then Mr. Mertins pulled the shift.

### B000005_092 · 同一角色

[接缝试听](audio/B000005_092.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： See, suddenly Juli's perfect answers, written in perfect cursive, were right across the aisle, just an eye-shot away. You wouldn't believe the number of answers I snagged from her. I started getting A's and B's on everything! It was great! But then Mr. Mertins pulled the shift. ｜  He had some new idea for “optimizing positional latitude and longitude,” and when the dust finally settled, I was sitting right in front of Juli Baker. This is where the sniffing comes in. That maniac started leaning forward and sniffing my hair.

预期读法： See, suddenly Juli's perfect answers, written in perfect cursive, were right across the aisle, just an eye-shot away. You wouldn't believe the number of answers I snagged from her. I started getting A's and B's on everything! It was great! But then Mr. Mertins pulled the shift. ｜  He had some new idea for “optimizing positional latitude and longitude,” and when the dust finally settled, I was sitting right in front of Juli Baker. This is where the sniffing comes in. That maniac started leaning forward and sniffing my hair.

### B000005_093 · 同一角色

[接缝试听](audio/B000005_093.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： He had some new idea for “optimizing positional latitude and longitude,” and when the dust finally settled, I was sitting right in front of Juli Baker. This is where the sniffing comes in. That maniac started leaning forward and sniffing my hair. ｜  She'd edge her nose practically up to my scalp and sniff-sniff-sniff. I tried elbowing and back-kicking. I tried scooting my chair way forward or putting my backpack between me and the seat. Nothing helped. She'd just scoot up, too, or lean over a little farther and sniff-sniff-sniff.

预期读法： He had some new idea for “optimizing positional latitude and longitude,” and when the dust finally settled, I was sitting right in front of Juli Baker. This is where the sniffing comes in. That maniac started leaning forward and sniffing my hair. ｜  She'd edge her nose practically up to my scalp and sniff-sniff-sniff. I tried elbowing and back-kicking. I tried scooting my chair way forward or putting my backpack between me and the seat. Nothing helped. She'd just scoot up, too, or lean over a little farther and sniff-sniff-sniff.

### B000005_094 · 同一角色

[接缝试听](audio/B000005_094.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： She'd edge her nose practically up to my scalp and sniff-sniff-sniff. I tried elbowing and back-kicking. I tried scooting my chair way forward or putting my backpack between me and the seat. Nothing helped. She'd just scoot up, too, or lean over a little farther and sniff-sniff-sniff. ｜  I finally asked Mr. Mertins to move me, but he wouldn't do it. Something about not wanting to disturb the delicate balance of educational energies. Whatever. I was stuck with her sniffing. And since I couldn't see her perfectly penned answers anymore, my grades took a dive. Especially in spelling.

预期读法： She'd edge her nose practically up to my scalp and sniff-sniff-sniff. I tried elbowing and back-kicking. I tried scooting my chair way forward or putting my backpack between me and the seat. Nothing helped. She'd just scoot up, too, or lean over a little farther and sniff-sniff-sniff. ｜  I finally asked Mr. Mertins to move me, but he wouldn't do it. Something about not wanting to disturb the delicate balance of educational energies. Whatever. I was stuck with her sniffing. And since I couldn't see her perfectly penned answers anymore, my grades took a dive. Especially in spelling.

### B000005_095 · 同一角色

[接缝试听](audio/B000005_095.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： I finally asked Mr. Mertins to move me, but he wouldn't do it. Something about not wanting to disturb the delicate balance of educational energies. Whatever. I was stuck with her sniffing. And since I couldn't see her perfectly penned answers anymore, my grades took a dive. Especially in spelling. ｜  Then one time, during a test, Juli's in the middle of sniffing my hair when she notices that I've blown a spelling word. A lot of words. Suddenly the sniffing stops and the whispering starts. At first I couldn't believe it. Juli Baker cheating?

预期读法： I finally asked Mr. Mertins to move me, but he wouldn't do it. Something about not wanting to disturb the delicate balance of educational energies. Whatever. I was stuck with her sniffing. And since I couldn't see her perfectly penned answers anymore, my grades took a dive. Especially in spelling. ｜  Then one time, during a test, Juli's in the middle of sniffing my hair when she notices that I've blown a spelling word. A lot of words. Suddenly the sniffing stops and the whispering starts. At first I couldn't believe it. Juli Baker cheating?

### B000005_096 · 同一角色

[接缝试听](audio/B000005_096.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： Then one time, during a test, Juli's in the middle of sniffing my hair when she notices that I've blown a spelling word. A lot of words. Suddenly the sniffing stops and the whispering starts. At first I couldn't believe it. Juli Baker cheating? ｜  But sure enough, she was spelling words for me, right in my ear. Juli'd always been sly about sniffing, which really bugged me because no one ever noticed her doing it, but she was just as sly about giving me answers, which was okay by me.

预期读法： Then one time, during a test, Juli's in the middle of sniffing my hair when she notices that I've blown a spelling word. A lot of words. Suddenly the sniffing stops and the whispering starts. At first I couldn't believe it. Juli Baker cheating? ｜  But sure enough, she was spelling words for me, right in my ear. Juli'd always been sly about sniffing, which really bugged me because no one ever noticed her doing it, but she was just as sly about giving me answers, which was okay by me.

### B000005_097 · 同一角色

[接缝试听](audio/B000005_097.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： But sure enough, she was spelling words for me, right in my ear. Juli'd always been sly about sniffing, which really bugged me because no one ever noticed her doing it, but she was just as sly about giving me answers, which was okay by me. ｜  The bad thing about it was that I started counting on her spelling in my ear. I mean, why study when you don't have to, right? But after a while, taking all those answers made me feel sort of indebted to her. How can you tell someone to bug off or quit sniffing you when you owe them?

预期读法： But sure enough, she was spelling words for me, right in my ear. Juli'd always been sly about sniffing, which really bugged me because no one ever noticed her doing it, but she was just as sly about giving me answers, which was okay by me. ｜  The bad thing about it was that I started counting on her spelling in my ear. I mean, why study when you don't have to, right? But after a while, taking all those answers made me feel sort of indebted to her. How can you tell someone to bug off or quit sniffing you when you owe them?

### B000005_098 · 同一角色

[接缝试听](audio/B000005_098.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： The bad thing about it was that I started counting on her spelling in my ear. I mean, why study when you don't have to, right? But after a while, taking all those answers made me feel sort of indebted to her. How can you tell someone to bug off or quit sniffing you when you owe them? ｜  It's, you know, wrong. So I spent the sixth grade somewhere between uncomfortable and unhappy, but I kept thinking that next year, next year, things would be different. We'd be in junior high — a big school — in different classes.

预期读法： The bad thing about it was that I started counting on her spelling in my ear. I mean, why study when you don't have to, right? But after a while, taking all those answers made me feel sort of indebted to her. How can you tell someone to bug off or quit sniffing you when you owe them? ｜  It's, you know, wrong. So I spent the sixth grade somewhere between uncomfortable and unhappy, but I kept thinking that next year, next year, things would be different. We'd be in junior high — a big school — in different classes.

### B000005_099 · 同一角色

[接缝试听](audio/B000005_099.wav) · [完整上下文](audio/chapter_000005_full.wav)

接缝在试听文件第 2.00 秒；短窗口两端是人工裁切边缘，不作为缺陷。

原文： It's, you know, wrong. So I spent the sixth grade somewhere between uncomfortable and unhappy, but I kept thinking that next year, next year, things would be different. We'd be in junior high — a big school — in different classes. ｜  It would be a world with too many people to worry about ever seeing Juli Baker again. It was finally, finally going to be over.

预期读法： It's, you know, wrong. So I spent the sixth grade somewhere between uncomfortable and unhappy, but I kept thinking that next year, next year, things would be different. We'd be in junior high — a big school — in different classes. ｜  It would be a world with too many people to worry about ever seeing Juli Baker again. It was finally, finally going to be over.
