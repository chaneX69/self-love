# self-love

以电影画面研究为依据的照片漫画动画转绘skill：先分析场景、材质、光照与反射，再在全部698帧、22,336个真实电影色卡中比较颜色，保留原照内容与身份，完成动画造型和印刷语言的整体重绘。

**公开仓库提供小样版，作者本机使用完整版。** 不提供ZIP发布附件，不将用户原照片、生成图或私人分析加入参考库。小样是电影局部原像素，不是重新生成的近似纹理；规则和全量数据不因小样化而删减。

## 目录

- [SKILL.md](SKILL.md)：统一入口、执行顺序、内容保护、风格与验收标准。
- [电影参考档案](references/library.html)：五维筛选、色卡、逐帧观察与直方图，可本地打开。
- [小样证据与双版本](references/crop-editions.md)：原坐标、像素哈希、上下文与验证边界。
- `data/`：698帧分类与学习记录、颜色比例、色阶、纹理特征和局部候选RLE。
- `assets/palette-crops/`：公开版698张图集，含22,336个128×128色卡上下文。
- `assets/crops/`：公开版548张纹理候选小样，保留重算所需边缘。
- [跨智能体接入](references/agent-compatibility.md)：Codex、Claude Code、WorkBuddy及豆包相关环境的能力契约。
- [照片隐私条款](references/photo-privacy.md)：不自行将上传照片留作模板、训练或微调依据。

## 使用

保留整个目录结构。把仓库放入目标智能体可读取的技能目录或工作区，按其实际支持的方式加载 `SKILL.md`。Codex附加配置在 `agents/openai.yaml`；其他宿主使用相同规则，不能假设存在同名工具。仅聊天、不能读文件或不能编辑参考图片的宿主不满足完整转绘能力，详见接入说明。

需要数值分析时，使用技能目录之外的Python环境安装依赖。Python 3.12为本次工程验证环境；不要把虚拟环境、照片、生成结果或私人报告写入此目录。

```bash
python -m pip install -r scripts/requirements.txt
python -B -m unittest discover -s scripts -p 'test_*.py'
python -B scripts/verify_crop_evidence.py
python -B scripts/verify_reference_privacy.py
```

小样验收命令用于公开小样版。本机完整版的全帧检查需其合法外部原件库，见[保留规范](references/library-retention.md)。照片匹配的计划、审批和输出均放在技能外私有目录，执行方式见[全库替色流程](references/full-library-workflow.md)。脚本检查通过不代替实际看图、材料判别或输出效果验收。

在 `git clone` 得到的仓库根目录运行隐私检查时，加 `--git-checkout` 排除经过Git确认的 `.git` 元数据；工作目录中未跟踪的文件仍会检查。这个选项不审计Git历史。安装到智能体的技能目录时不携带 `.git`，运行默认检查。

## 已知边界

- 698帧已归档四类纹理的类别复核；548个局部接受候选可重算。全帧真实语义像素占比仍未完成，保持 `null`，不能把阈值候选称为真值。
- 小样可核对保存区域的原像素，但不能还原整帧空间、未保存表面或完整构图。使用时必须确认上下文足够，不足则停止该候选批准。
- 单张照片按五项画面指标综合至少90%验收；生成器不保证逐像素HEX、逐字或几何完全一致。输出需另行实际检查。
- 多宿主文档共用，不代表Claude Code、WorkBuddy、豆包、Windows或Linux已完成真实出图实测。工程验证、宿主验证、视觉验收和用户批准分别记录。
- 电影小样不在MIT授权范围。作者要求公开上传，但未提供电影素材再分发许可证明；分析或裁切不自动取得第三方权利。

原创代码、规则与原创文字分析采用[MIT](LICENSE.md)；电影素材与第三方内容见[权利说明](THIRD_PARTY_NOTICES.md)。发布条件与状态见[发布边界](references/release-readiness.md)。
