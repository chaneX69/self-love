# 官方依据与证据分级

制作资料核验：2026-09-29；2026-09-30重新核验S1／S3的印刷式景深、运动色移及光效网点；新增剧情范围核验：2026-09-30。当前范围为迈尔斯本土与彼得B原生世界及其制作基础；合并来自用户授权，不伪称官方认定两世界参数相同。其他未获准世界不引用到提示中。

## 制作团队直接说明

- **S1 制作公司**：[Sony Pictures Imageworks 第一部制作拆解](https://www.imageworks.com/node/1371)。已读正文。设计意图主导，人物表达线与硬表面结构线经过制作，印刷网点／排线和色版偏移参与成片；不意味着一键照片滤镜。
- **S2 厂商官网具名团队访谈**：[Foundry Look Development and Texturing](https://www.foundry.com/insights/film-tv/into-spiderverse)。已读相关正文，Bret St Clair／Edwin Fabros。Mari 分层绘制角色、环境、道具；Katana／Arnold 和 Nuke 协作，部分控制通过 AOV 交给合成艺术家按镜头调整。只据此确定分层设计流程，不推导未公开的材质参数。
- **S3 厂商官网具名团队访谈**：[Foundry Graphic Look in Comp](https://www.foundry.com/insights/film-tv/graphic-look-in-comp-spiderman)。已读相关正文，Geeta Basantani／Marco Recuay。排线和网点粗细、尺寸、角度、间隔可依据光照明暗调整；车站光效及迈尔斯轮廓光也可用网点表达。说明点阵有时属于光，不都是表面花纹。
- **S4 厂商官网团队访谈**：[Foundry Across the Spider-Verse](https://www.foundry.com/insights/film-tv/across-the-spider-verse-nuke-mari-katana)。仅采用明确指向 Miles' world 的“排线构造阴影”段落，其他世界做法不纳入本库。
- **S5 厂商官网 FX 团队材料**：[SideFX Into the Spider-Verse](https://www.sidefx.com/community/spider-man-into-the-spider-verse/)。已读正文，Pav Grochola 等一手说明支持图形化 FX 与有设计的故障，不依赖评论区身份。

本轮S1补充：以印刷色层不对齐表现失焦，并用形体拖伸、速度线等图形化方法处理高速运动。S3补充：ChromaShifter原为基于深度的色偏工具，后使用运动矢量产生拖尾；灯光效果和轮廓光可带网点。只证明这些方法存在，不证明405–438每一处彩边的具体实现，也不等于禁止照片应用中一切柔和模糊。用户明确允许远处建筑、人群模糊属于定制目标；将其落实为分层减细节、柔化与色偏是本技能应用策略。

## 设计与资料入口

- [Patrick O'Keefe 官方履历](https://www.sonypicturesanimation.com/our-team/artists/patrick-okeefe)核实创作者职务；[本人作品集](https://okeefe.artstation.com/projects/JlOeZZ)的 Brooklyn／Manhattan／店铺题名作为日常场景入口。页面文字已读，不声称所有图均精读。
- [ADG 制作设计提交 PDF](https://assets.adg.org/media/submissions/2023-11-28_15-24-54/WAM_ADG_Awards.pdf)为团队提交一手材料。本库仅采用 p2–3 城市／室内观察；全片资料中其他页不用于风格规则。不是 Sony 企业公告。
- [SIGGRAPH 2019 制作专场](https://www.siggraph.org/wp-content/uploads/2019/07/Open-Access-for-SIGGRAPH-2019-Production-Sessions.html)及 [Inklines 讲座公告](https://san-francisco.siggraph.org/2024/05/17/swing-behind-the-scenes-of-spider-man-across-the-spider-verse-with-inkline/)仅核实公告，未观看完整讲座。
- [第一部 Titan 正版设定集](https://titanbooks.com/9653-spider-man-into-the-spider-verse-the-art-of-the-movie/)与[第二部 Abrams 正版设定集](https://www.abramsbooks.com/product/spider-man-across-the-spider-verse-the-art-of-the-movie_9781419763991/)仅查目录，未通读书籍。
- [Imageworks Building New York City](https://www.youtube.com/watch?v=vH-LpARZurY)已核实官方入口，未获得可用字幕或完成逐镜头学习。不能将视频标题写成已吸收的制作细节。

## 四种证据不可互换

2026-09-30全库审计：01–698全部重新测量、场景级复看与标签化，682活跃（474常规、208条件）、16归档；每帧32个原像素代表色、RGB/L*直方图、色相明度交叉与3×3位置统计。当前入口见[色阶方法](color-value-relationships.md)。此前各批“未测色”和计数只描述历史，不再作为当前入口。687–689仍依据结尾序列推断彼得B原生街区，未新增外部时间码核证；换光序列仍非严格曝光实验。所有数值是截图测量，不是官方制作参数。本轮新增算法依据为scikit-image官方CIELAB/CIEDE2000文档，未声称重新访问下列全部制作来源。

此前594–637新增44条截图观察及测色，常规暖厅／冷机房与条件能量／故障分开。当时覆盖01–637，621张活跃、16张仅归档；世界归类依据用户上传连续场景与可见环境，碰撞场内漂浮城市不等于新原生世界日常画风。

此前526–593新增68条截图观察，城市配色／建筑表现见[专项](city-color-architecture.md)。已编号01–593另完成明度与颜色联合采样，当时577张活跃、16张仅归档；这取代下述历史批次“未追加测色”的状态，但不把截图统计称作官方色板、物体分割、真实曝光或材质参数。数学来源与采样限制在方法页，原有制作来源不因此变成这批数值的官方背书。

2026-09-30另读[Sony公开剧本](https://origin-flash.sonypictures.com/ist/awards_screenplays/SV_screenplay.pdf?file=DOCUMENT)印刷页43–48相关段落，用于224–265批次的墓地／到达前回顾／穿越／时代广场／葬礼／追逐范围核对。只核实叙事顺序，不将剧本形容词当shader参数，也不声称通读剧本或核实每个成片时间码。

1. 官方／具名团队事实：以上来源能直接支持的简短结论。
2. 用户截图观察：活跃编号14–226、228–239及242–525中的可见颜色、边缘、纹理、光泽和空间关系，不等于知道底层 shader；227及240–241未进入运行参考。266–283、284–330与331–387的人脸／材质／反射／故障／动作分析均是用户供图观察，未追加官方制作参数或测色数据；330–331屏内图像另标二次内容，不视作现场整体异常。331–387按实验室至雪林的场景连续性归类，不声称追加核对电影时间码。388–404为用户提供的两组同场景光照对照，排除广告换画／姿态／取景变化后作定性观察；未确认准确时间、天气成因、像素配准、灯光输出或材质参数。405–438记录透明多边形光斑、点阵光边、建筑分色与清晰度层级；远处人群概括是用户授权的照片应用，未冒称该批验证过所有密集人群。 439–441补充暗室彩光、留黑与远处焦点观察，未追加官方灯具、曝光或材质参数。 442–521新增80帧展柜、夜街、暖窗与条件图形；圆形网点车灯光晕、静态反应中的强彩边、软窗格和多层玻璃为用户截图观察，不推断特定光学设备、运动矢量、参数或抽帧时长。 522–525为四张相近机位桥梁夕照，云形和取景差异另列；窄亮线仅按可见形态记录，不指定反射／自发光比例、精准时间或新官方参数。
3. 应用推论：为真实照片拟定的造型、材质、光影步骤。清楚标为本技能策略，不冠以“官方参数”。
4. 用户定制：三层纹理、身体双彩错版、按人数的感应模式，以及按照片主动匹配图形动效、内心文字先建议一句待确认，不宣称电影每帧如此。轻／中／强图形等级是照片应用策略，不是官方力度公式。

没有证据支持固定 roughness 数值、金属度／IOR、禁用一切 AO／反弹光、全部高光手绘、固定灯数或官方 HEX。截图受片源、缩放和压缩影响，细网纹还可能包含采样伪影；不把每一个像素花纹都归因于原始制作。
