import argparse
import ctypes
import os
import platform
import sys
import time
import traceback
import cv2
import mss
import numpy as np
import pyautogui

# OS별 디스플레이 배율(DPI) 처리
if platform.system() == "Windows":
    try:
        # 윈도우 OS의 배율 설정을 프로세스에 적용하여 mss와 pyautogui의 좌표계를 통일
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_monitor_scaling(x=None, y=None):
    """
    논리 해상도와 물리 해상도를 비교하여 배율(Scale)을 계산합니다.
    마우스 커서 (x, y) 위치가 주어질 경우 해당 모니터를 우선 탐색합니다.
    """
    with mss.mss() as sct:
        logical_w, logical_h = pyautogui.size()
        if len(sct.monitors) > 1:
            primary = sct.monitors[1]
            physical_w = primary["width"]
        else:
            physical_w = sct.monitors[0]["width"]

        if logical_w == 0:
            return 1.0
        return physical_w / logical_w


def capture_region(sct, scale, x, y, size):
    """논리 좌표 (x, y) 주변의 size 크기 영역을 물리 좌표로 변환하여 캡처합니다."""
    px, py = int(x * scale), int(y * scale)
    psize = int(size * scale)

    left = px - psize // 2
    top = py - psize // 2

    region = {"top": top, "left": left, "width": psize, "height": psize}
    screenshot = sct.grab(region)

    img = np.array(screenshot)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR), (left, top)


def find_match(img_bgr, template_path, threshold=0.7):
    """OpenCV를 사용하여 이미지 내에서 템플릿을 찾습니다."""
    if not os.path.exists(template_path):
        return None, 0

    template = cv2.imread(template_path)
    if template is None:
        return None, 0

    # 캡처 영역이 템플릿보다 작으면 매칭 불가
    th, tw = template.shape[:2]
    ih, iw = img_bgr.shape[:2]
    if ih < th or iw < tw:
        return None, 0

    res = cv2.matchTemplate(img_bgr, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    if max_val >= threshold:
        center = (max_loc[0] + tw // 2, max_loc[1] + th // 2)
        return center, max_val
    return None, max_val


def capture_template_mode(template_path="button.jpg", capture_size=60):
    """사용자가 직접 템플릿 이미지를 캡처할 수 있도록 도와주는 모드입니다."""
    print(f"\n[캡처 모드] 마우스 커서를 클릭할 버튼의 '정중앙'에 올리세요.")
    print(f"3초 후에 커서 주변 {capture_size}x{capture_size} 영역을 캡처합니다...")
    for i in range(3, 0, -1):
        print(f"{i}...")
        time.sleep(1)

    x, y = pyautogui.position()
    scale = get_monitor_scaling(x, y)

    with mss.mss() as sct:
        img, _ = capture_region(sct, scale, x, y, capture_size)
        cv2.imwrite(template_path, img)
        print(f"\n[성공] '{template_path}' 저장 완료! (크기: {img.shape[1]}x{img.shape[0]}px)")
        print("이제 일반 모드로 실행하세요: python button_clicker.py")


def auto_clicker(args):
    template_path = args.template
    search_size = args.search_size
    threshold = args.threshold
    cooldown = args.cooldown
    interval = args.interval
    debug = args.debug

    if not os.path.exists(template_path):
        print(f"[오류] '{template_path}' 파일이 없습니다.")
        print(f"팁: 'python button_clicker.py --capture -t {template_path}' 명령어로 템플릿을 생성할 수 있습니다.")
        return

    print("\n==========================================")
    print("       Smart Button Clicker 실행 중       ")
    print("==========================================")
    scale = get_monitor_scaling()
    print(f"[정보] 시스템 배율: {scale * 100:.0f}%")
    print(f"[설정] 템플릿 파일: {template_path}")
    print(f"[설정] 탐색 영역: {search_size}x{search_size} px | 일치도 임계값: {threshold:.2f}")
    print(f"[설정] 클릭 쿨다운: {cooldown}초 | 검사 주기: {interval}초")
    print("[안내] 중단하려면 Ctrl+C를 누르세요.\n")

    last_debug_time = 0

    with mss.mss() as sct:
        while True:
            x, y = pyautogui.position()

            try:
                # 1. 커서 주변 영역 캡처
                img, (phys_left, phys_top) = capture_region(sct, scale, x, y, search_size)

                # 2. 이미지 매칭
                match_local, score = find_match(img, template_path, threshold)

                if debug and (time.time() - last_debug_time > 1.0):
                    print(f"[디버그] 현재 최고 일치도: {score:.3f} / {threshold:.2f} (마우스: {x}, {y})")
                    last_debug_time = time.time()

                if match_local:
                    # 3. 물리 좌표 -> 논리 좌표 변환
                    gx = (phys_left + match_local[0]) / scale
                    gy = (phys_top + match_local[1]) / scale

                    print(f"\n[!] 타깃 발견! (정확도: {score:.2f}, 목표 좌표: {gx:.0f}, {gy:.0f})")

                    # 4. 클릭 수행 (현재 마우스 위치 기억 후 복구)
                    ox, oy = pyautogui.position()
                    pyautogui.click(gx, gy)
                    pyautogui.moveTo(ox, oy)
                    print(f"[+] 클릭 완료 및 커서 복귀 ({ox}, {oy}) -> 쿨다운 {cooldown}초 대기")

                    time.sleep(cooldown)

            except Exception as e:
                if debug:
                    traceback.print_exc()

            time.sleep(interval)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="마우스 주변을 감시하여 지정 버튼을 자동으로 클릭하는 스마트 매크로"
    )
    parser.add_argument(
        "-t", "--template",
        default="button.jpg",
        help="클릭할 대상 템플릿 이미지 경로 (기본값: button.jpg)"
    )
    parser.add_argument(
        "-th", "--threshold",
        type=float,
        default=0.7,
        help="템플릿 매칭 일치도 임계값 (0.0 ~ 1.0, 기본값: 0.7)"
    )
    parser.add_argument(
        "-s", "--search-size",
        type=int,
        default=200,
        help="마우스 주변 감시 영역 크기(픽셀, 기본값: 200)"
    )
    parser.add_argument(
        "-c", "--cooldown",
        type=float,
        default=1.5,
        help="클릭 후 재작동 대기 시간(초, 기본값: 1.5)"
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=0.05,
        help="화면 감시 주기(초, 기본값: 0.05)"
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="현재 마우스 위치를 캡처하여 템플릿 이미지를 생성하는 모드"
    )
    parser.add_argument(
        "--capture-size",
        type=int,
        default=60,
        help="캡처 모드에서 저장할 영역 크기(픽셀, 기본값: 60)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="실시간 매칭 점수 및 상세 디버그 로그 출력"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    try:
        if args.capture:
            capture_template_mode(args.template, args.capture_size)
        else:
            auto_clicker(args)
    except KeyboardInterrupt:
        print("\n[종료] 사용자에 의해 프로그램을 종료합니다.")
