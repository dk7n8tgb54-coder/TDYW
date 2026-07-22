# -*- coding: utf-8 -*-
"""
为 5 个压测账号(st_press_01~05)批量灌入电子签名。

背景
----
department_duty_log 的签署依赖账号本人的电子签名(AccountSignature)。签名只能由
超管通过 SupperOnlyView 设置,普通压测账号无法自助设置,因此压测时签署必然返回
"未配置有效签名"、导出必然返回"没有可导出的已签记录",造成 sign 50% / export 54% 的
"失败"——这 100% 是测试数据缺陷,而非被测系统缺陷。

本脚本用超管身份为每个压测账号生成一张 PNG 签名图并调用 signature.set_signature,
使签名正确绑定到该账号(object_id/tenant/module/type),压测即可跑通真实签署 + 导出链路。

运行方式(Docker 容器内,沿用 create_stress_accounts.py 约定)
---------------------------------------------------------
    docker exec -i tdyw python manage.py shell < locustfile/tools/provision_stress_signatures.py

说明
----
- 自动取库中第一个 is_supper=True 的账号作为操作人(operator)。
- 幂等:重复运行会覆盖/更新已有签名。
- 需要压测角色的 department_duty_log 具备 sign/create/edit/del/export 权限
  (生产 tdyw 复用现有账号,权限通常已具备;否则先跑 create_stress_accounts.py)。
- 口径与 create_stress_accounts.py 的 STRESS_USERNAMES 保持一致,改动需同步。
"""
import io

from PIL import Image, ImageDraw, ImageFont
from django.core.files.uploadedfile import InMemoryUploadedFile
from apps.account.models import User
from apps.signature import services as signature_services

STRESS_USERNAMES = ["st_press_01", "st_press_02", "st_press_03", "st_press_04", "st_press_05"]


def make_signature_image(text):
    """生成一张 480x180 的 PNG 签名图(白底 + 用户名 + 基线)。"""
    w, h = 480, 180
    img = Image.new("RGB", (w, h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 64)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((w - tw) / 2 - bbox[0], (h - th) / 2 - bbox[1]),
              text, fill=(20, 20, 20), font=font)
    draw.line([(40, h - 40), (w - 40, h - 40)], fill=(20, 20, 20), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_uploaded(png_bytes, name):
    return InMemoryUploadedFile(
        io.BytesIO(png_bytes), field_name="file", name=name,
        content_type="image/png", size=len(png_bytes), charset=None,
    )


def main():
    superuser = User.objects.filter(is_supper=True).first()
    if not superuser:
        print("ERROR: 未找到 is_supper=True 的超管账号,无法灌签名")
        return
    print(f"[info] 操作人(超管): {superuser.username}")

    ok, skip, fail = 0, 0, 0
    for username in STRESS_USERNAMES:
        user = User.objects.filter(username=username).first()
        if not user:
            print(f"[跳过] 账号 {username} 不存在")
            skip += 1
            continue
        png = make_signature_image(username)
        uploaded = build_uploaded(png, f"{username}_signature.png")
        try:
            sig = signature_services.set_signature(
                operator=superuser, target_user_id=user.id, image_file=uploaded)
            sig_id = getattr(sig, "id", None)
            print(f"[OK] {username} (id={user.id}) 已设置签名 sig_id={sig_id}")
            ok += 1
        except Exception as e:
            print(f"[失败] {username}: {e}")
            fail += 1
    print(f"\n完成: 成功 {ok} / 跳过 {skip} / 失败 {fail}")


main()
