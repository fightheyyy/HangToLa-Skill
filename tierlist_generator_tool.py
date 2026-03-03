"""
Tier List Generator Tool - 把评价结果渲染到 tier list 模板图上
输入各维度的评级，输出一张填好内容的 tier list 图片。
支持两种标签类型：
  - summary（深色橙色）：多skills场景 或 单skill的skillname
  - dim（浅色蓝灰）：单skill的维度评价
自适应宽度：根据内容自动扩展图片宽度。
"""

import sys
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tools', 'global'))

from base_tool import BaseTool
from typing import Dict, Any, List
from PIL import Image, ImageDraw, ImageFont
import time

# 模板图路径
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'image.png')

# 左侧 tier 标签栏宽度（根据模板调整）
TIER_LABEL_WIDTH = 190
# tier 标签行高
TIER_ROW_HEIGHT = 155

# 内容区参数
TAG_PADDING = 16  # 标签之间间距
TAG_INNER_PAD = 12  # 标签内边距
TAG_RADIUS = 8  # 标签圆角

# 标签背景色
TAG_BG_SUMMARY = (220, 120, 20)  # 总评/skillname：橙色（深色）
TAG_BG_DIM = (100, 130, 160)     # 维度：蓝灰色（浅色）
TAG_TEXT_COLOR = (255, 255, 255)

# 右侧内容区背景色（用于扩展区域）
CONTENT_BG_COLOR = (200, 200, 200)


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


def _parse_item(item):
    """解析标签项"""
    if isinstance(item, str):
        return item, "summary"
    if isinstance(item, dict):
        return item.get("name", ""), item.get("type", "summary")
    return str(item), "summary"


def calculate_tier_width(tier_data: Dict, font, font_summary) -> int:
    """计算每个 tier 需要的宽度"""
    tier_widths = {}
    for tier_name, items in tier_data.items():
        if not items:
            tier_widths[tier_name] = 0
            continue
        x = 0
        for item in items:
            if isinstance(item, str):
                name = item
                tag_type = "summary"
            else:
                name, tag_type = _parse_item(item)
            if not name:
                continue
            cur_font = font_summary if tag_type == "summary" else font
            bbox = cur_font.getbbox(name)
            tw = bbox[2] - bbox[0]
            tag_w = tw + TAG_INNER_PAD * 2
            x += tag_w + TAG_PADDING
        tier_widths[tier_name] = x - TAG_PADDING if x > 0 else 0
    return tier_widths


class TierListGenerator(BaseTool):
    """Tier List 图片生成工具"""

    tool_name = "tierlist_generator"
    tool_description = (
        "把评价结果渲染到 tier list 模板图上。"
        "每个标签可以是纯字符串（默认深色总评标签），"
        "也可以是 {name, type} 对象（type='dim' 浅色维度标签，type='summary' 深色总评标签）。"
        "自动根据内容宽度扩展图片。"
    )
    tool_parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "评价对象名称（可选）"
            },
            "tiers": {
                "type": "object",
                "description": (
                    "各等级对应的标签列表。key 为等级名（夯/顶级/人上人/NPC/拉完了），"
                    "value 为数组，元素可以是纯字符串或 {name, type} 对象。"
                    "type='summary' 深色总评标签（默认），type='dim' 浅色维度标签。"
                )
            }
        },
        "required": ["tiers"]
    }
    tool_timeout = 30

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.validate_params(params, ['tiers'])

        tier_data = params['tiers']
        title = params.get('title', '')

        # 加载模板图片
        if not os.path.exists(TEMPLATE_PATH):
            return {'error': f'模板图片不存在: {TEMPLATE_PATH}'}

        template_img = Image.open(TEMPLATE_PATH).convert('RGBA')
        template_width, template_height = template_img.size

        # 字体
        font = find_font(22)
        font_summary = find_font(26)

        # 计算实际内容宽度
        tier_widths = calculate_tier_width(tier_data, font, font_summary)
        actual_content_width = max(tier_widths.values()) if tier_widths else 0

        # 计算需要的总宽度
        min_content_width = TAG_PADDING * 2
        needed_width = TIER_LABEL_WIDTH + max(actual_content_width + TAG_PADDING * 2, min_content_width)

        # 如果需要扩展宽度
        if needed_width > template_width:
            extension_width = needed_width - template_width
            # 创建新画布（扩展宽度）
            new_img = Image.new('RGBA', (needed_width, template_height))
            # 粘贴模板图片
            new_img.paste(template_img, (0, 0), template_img)
            # 复制模板右侧边缘一列像素，重复填充扩展区域
            # 取模板最右侧一列
            edge_column = template_img.crop((template_width - 1, 0, template_width, template_height))
            # 拉伸填充到扩展区域
            stretched_edge = edge_column.resize((extension_width, template_height))
            new_img.paste(stretched_edge, (template_width, 0))
            img = new_img
            # 更新画布总宽度（用于后续计算）
            template_width = needed_width
        else:
            img = template_img.copy()

        draw = ImageDraw.Draw(img)

        # 绘制标签
        content_start_x = TIER_LABEL_WIDTH + TAG_PADDING
        y = 0
        tier_order = ['夯', '顶级', '人上人', 'NPC', '拉完了']

        for tier_name in tier_order:
            items = tier_data.get(tier_name, [])
            if not items:
                y += TIER_ROW_HEIGHT
                continue

            x = content_start_x
            for item in items:
                if isinstance(item, str):
                    name = item
                    tag_type = "summary"
                else:
                    name, tag_type = _parse_item(item)
                if not name:
                    continue

                cur_font = font_summary if tag_type == "summary" else font
                bg_color = TAG_BG_SUMMARY if tag_type == "summary" else TAG_BG_DIM

                bbox = cur_font.getbbox(name)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tag_w = tw + TAG_INNER_PAD * 2
                tag_h = th + TAG_INNER_PAD * 2
                ty = y + (TIER_ROW_HEIGHT - tag_h) // 2

                # 画圆角矩形背景
                draw.rounded_rectangle(
                    [x, ty, x + tag_w, ty + tag_h],
                    radius=TAG_RADIUS,
                    fill=bg_color
                )
                # 总评标签加白色边框
                if tag_type == "summary":
                    draw.rounded_rectangle(
                        [x, ty, x + tag_w, ty + tag_h],
                        radius=TAG_RADIUS,
                        outline=(255, 255, 255),
                        width=2
                    )
                # 画文字
                text_x = x + TAG_INNER_PAD
                text_y = ty + TAG_INNER_PAD - bbox[1]
                draw.text((text_x, text_y), name, fill=TAG_TEXT_COLOR, font=cur_font)
                x += tag_w + TAG_PADDING

            y += TIER_ROW_HEIGHT

        # 直接保存为PNG（保持RGBA格式）
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'extracted')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'tierlist_{int(time.time())}.png')
        img.save(out_path, 'PNG')

        return {
            'file_path': os.path.abspath(out_path),
            'file_name': os.path.basename(out_path),
            'message': 'Tier list 图片已生成，请用 send_file 发送给用户'
        }


if __name__ == '__main__':
    tool = TierListGenerator()
    tool.run()
