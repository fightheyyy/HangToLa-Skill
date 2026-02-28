"""
Tier List Generator Tool - 把评价结果渲染到 tier list 模板图上
输入各维度的评级，输出一张填好内容的 tier list 图片。
"""

import sys
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')



from base_tool import BaseTool
from typing import Dict, Any, List
from PIL import Image, ImageDraw, ImageFont
import time

# 模板图路径
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image.png')

# 每个 tier 行的 Y 范围和文字垂直居中位置
TIERS = {
    '夯':    {'y1': 0,   'y2': 148, 'cy': 74},
    '顶级':  {'y1': 155, 'y2': 310, 'cy': 232},
    '人上人': {'y1': 318, 'y2': 477, 'cy': 397},
    'NPC':   {'y1': 483, 'y2': 642, 'cy': 562},
    '拉完了': {'y1': 648, 'y2': 797, 'cy': 722},
}

# 内容区起始 X
CONTENT_X = 190
# 每个标签之间的间距
TAG_PADDING = 16
# 标签内边距
TAG_INNER_PAD = 12
# 标签圆角
TAG_RADIUS = 8
# 标签背景色（半透明深色）
TAG_BG = (40, 40, 40, 200)
# 标签文字色
TAG_TEXT_COLOR = (255, 255, 255)


def find_font(size: int) -> ImageFont.FreeTypeFont:
    """尝试加载中文字体"""
    candidates = [
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
        'C:/Windows/Fonts/simsun.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    ]
    for fp in candidates:
        if os.path.exists(fp):
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


class TierListGenerator(BaseTool):
    """Tier List 图片生成工具"""

    tool_name = "tierlist_generator"
    tool_description = "把夯到拉评价结果渲染到 tier list 模板图上，生成一张排位图片。"
    tool_parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "评价对象名称，显示在图片上（可选）"
            },
            "tiers": {
                "type": "object",
                "description": "各等级对应的维度列表。key 为等级名（夯/顶级/人上人/NPC/拉完了），value 为该等级下的维度名数组",
                "properties": {
                    "夯": {"type": "array", "items": {"type": "string"}},
                    "顶级": {"type": "array", "items": {"type": "string"}},
                    "人上人": {"type": "array", "items": {"type": "string"}},
                    "NPC": {"type": "array", "items": {"type": "string"}},
                    "拉完了": {"type": "array", "items": {"type": "string"}}
                }
            }
        },
        "required": ["tiers"]
    }
    tool_timeout = 30

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_params(params, ['tiers'])

        tier_data = params['tiers']
        title = params.get('title', '')

        # 打开模板
        img = Image.open(TEMPLATE_PATH).convert('RGBA')
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font = find_font(28)
        title_font = find_font(22)

        # 逐 tier 渲染标签
        for tier_name, dims in tier_data.items():
            if tier_name not in TIERS or not dims:
                continue
            info = TIERS[tier_name]
            cy = info['cy']
            x = CONTENT_X

            for dim in dims:
                bbox = font.getbbox(dim)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tag_w = tw + TAG_INNER_PAD * 2
                tag_h = th + TAG_INNER_PAD * 2

                ty = cy - tag_h // 2

                # 画圆角矩形背景
                draw.rounded_rectangle(
                    [x, ty, x + tag_w, ty + tag_h],
                    radius=TAG_RADIUS,
                    fill=TAG_BG
                )
                # 画文字
                draw.text(
                    (x + TAG_INNER_PAD, ty + TAG_INNER_PAD - bbox[1]),
                    dim, fill=TAG_TEXT_COLOR, font=font
                )
                x += tag_w + TAG_PADDING

        # 合成
        result = Image.alpha_composite(img, overlay).convert('RGB')

        # 保存
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'extracted')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'tierlist_{int(time.time())}.png')
        result.save(out_path, 'PNG')

        return {
            'file_path': os.path.abspath(out_path),
            'file_name': os.path.basename(out_path),
            'message': 'Tier list 图片已生成，请用 send_file 发送给用户'
        }


if __name__ == '__main__':
    tool = TierListGenerator()
    tool.run()
