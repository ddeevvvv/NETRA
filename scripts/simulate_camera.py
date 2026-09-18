import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import cv2
import numpy as np

def find_ffmpeg_executable():
    """Finds system ffmpeg on PATH or common macOS/Windows install locations."""
    path = shutil.which("ffmpeg")
    if path:
        return path
    
    # Common install locations
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    candidates = [
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        os.path.join(local_app_data, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe", "ffmpeg-9.0.1-full_build", "bin", "ffmpeg.exe"),
        os.path.join(program_files, "ffmpeg", "bin", "ffmpeg.exe"),
        "C:\\ffmpeg\\bin\\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def enumerate_avfoundation_devices():
    """Enumerates available video capture devices on macOS via ffmpeg avfoundation."""
    ffmpeg_bin = find_ffmpeg_executable()
    if not ffmpeg_bin:
        print("\n" + "!" * 80)
        print("[CRITICAL ERROR] FFmpeg executable not found on macOS.")
        print("!" * 80)
        print("Please install FFmpeg via Homebrew: brew install ffmpeg\n")
        raise RuntimeError("FFmpeg required for macOS camera enumeration.")
    
    res = subprocess.run(
        [ffmpeg_bin, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True
    )
    
    devices = []
    in_video_section = False
    for line in res.stderr.splitlines():
        if "AVFoundation video devices:" in line:
            in_video_section = True
            continue
        if in_video_section and ("AVFoundation audio devices:" in line or ("[" not in line and "AVFoundation" not in line)):
            in_video_section = False
            continue
        if in_video_section:
            m = re.search(r"\]\s*\[(\d+)\]\s+(.*)", line)
            if m:
                idx = int(m.group(1))
                name = m.group(2).strip()
                devices.append((idx, name, "AVFoundation"))
    return devices

def list_available_devices():
    """Enumerates available video capture devices (AVFoundation on macOS, DirectShow on Windows)."""
    print("\n" + "=" * 65)
    print(" IBVAP Camera Device Enumeration Helper")
    print("=" * 65)
    
    devices = []
    if platform.system() == "Darwin":
        try:
            devices = enumerate_avfoundation_devices()
        except Exception as e:
            print(f"[WARN] AVFoundation enumeration error: {e}")
    elif platform.system() == "Windows":
        try:
            from pygrabber.dshow_graph import FilterGraph
            dshow_names = FilterGraph().get_input_devices()
            for idx, name in enumerate(dshow_names):
                devices.append((idx, name, "DirectShow"))
        except Exception as e:
            print(f"[WARN] pygrabber DirectShow enumeration error: {e}")

    if not devices and platform.system() != "Darwin":
        # Fallback to probing OpenCV indices 0..5 on non-macOS systems
        for i in range(6):
            backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    devices.append((i, f"Camera Device Index #{i}", "OpenCV"))
                cap.release()

    if devices:
        print(f"Found {len(devices)} available video input device(s):\n")
        for idx, name, source in devices:
            print(f"  [{idx}] \"{name}\"  (Backend: {source})")
        print("\nUsage Examples:")
        print(f"  python scripts/simulate_camera.py --input {devices[0][0]} --stream-name cam1")
        if platform.system() == "Windows":
            print(f'  python scripts/simulate_camera.py --input "{devices[0][1]}" --stream-name cam1')
        elif platform.system() == "Darwin":
            print(f'  python scripts/simulate_camera.py --input {devices[0][0]} --stream-name cam1')
    else:
        print(" [!] No active video capture devices found.")
        print(" Ensure your webcam is connected and not locked by another process.")

    print("=" * 65 + "\n")
    return devices

def get_webcam_capture(input_str: str):
    """
    Resolves input_str to an open cv2.VideoCapture instance (for video files or Windows DirectShow).
    Raises RuntimeError loud and clear if capture fails — NO SILENT TEST PATTERNS!
    """
    is_file = False
    cap = None
    resolved_description = ""

    # Case 1: Video file path
    if os.path.isfile(input_str):
        resolved_description = f"Video File '{os.path.abspath(input_str)}'"
        cap = cv2.VideoCapture(input_str)
        is_file = True

    # Case 2: Integer device index (e.g. "0", "1")
    elif input_str.isdigit():
        idx = int(input_str)
        dev_name = f"Index #{idx}"
        if platform.system() == "Windows":
            try:
                from pygrabber.dshow_graph import FilterGraph
                names = FilterGraph().get_input_devices()
                if idx < len(names):
                    dev_name = f"'{names[idx]}' (Index #{idx})"
            except Exception:
                pass
            resolved_description = f"Windows DirectShow Webcam {dev_name}"
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
        else:
            resolved_description = f"Webcam Index #{idx}"
            cap = cv2.VideoCapture(idx)

    # Case 3: Device name string on Windows (e.g. "USB2.0 HD UVC WebCam")
    elif platform.system() == "Windows":
        try:
            from pygrabber.dshow_graph import FilterGraph
            dshow_names = FilterGraph().get_input_devices()
            if input_str in dshow_names:
                idx = dshow_names.index(input_str)
                resolved_description = f"DirectShow Device '{input_str}' (Index #{idx})"
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        except Exception:
            pass

    # LOUD FAILURE CHECK — No silent fallback to test patterns!
    if cap is None or not cap.isOpened():
        print("\n" + "!" * 80)
        print(f"[CRITICAL ERROR] Unable to open capture source: '{input_str}'")
        print("!" * 80)
        print("Possible causes:")
        print("  1. Webcam is unplugged or disabled in OS settings.")
        print("  2. Webcam is currently locked by another application (Zoom, Teams, Chrome, etc.).")
        print("  3. Invalid input file path or non-existent device name.")
        print("\nRun the device list helper to view valid connected webcams:")
        print("  python scripts/simulate_camera.py --list-devices\n")
        raise RuntimeError(f"Failed to open video source '{input_str}'")

    # Test reading initial frame to verify device is operational
    ret, test_frame = cap.read()
    if not ret or test_frame is None:
        cap.release()
        print("\n" + "!" * 80)
        print(f"[CRITICAL ERROR] Opened {resolved_description}, but failed to read initial frame.")
        print("!" * 80)
        print("The webcam device opened but returned no frame buffer (device busy or locked).\n")
        raise RuntimeError(f"Webcam '{input_str}' returned empty frame buffer.")

    print(f"[SIM] Successfully acquired stream from {resolved_description} (Frame size: {test_frame.shape[1]}x{test_frame.shape[0]})")
    return cap, is_file, resolved_description

def stream_camera_mac(input_str: str, stream_name: str, rtsp_url: str):
    """Streams from macOS AVFoundation webcam directly via FFmpeg into MediaMTX RTSP server."""
    ffmpeg_bin = find_ffmpeg_executable()
    if not ffmpeg_bin:
        print("\n" + "!" * 80)
        print("[CRITICAL ERROR] FFmpeg executable not found on macOS.")
        print("!" * 80)
        print("Please install FFmpeg via Homebrew: brew install ffmpeg\n")
        raise RuntimeError("FFmpeg required for macOS camera streaming.")

    # Resolve device index
    devices = enumerate_avfoundation_devices()
    dev_name = f"Device #{input_str}"
    target_idx = None

    if input_str.isdigit():
        target_idx = int(input_str)
        for idx, name, _ in devices:
            if idx == target_idx:
                dev_name = f"'{name}' (Index #{idx})"
                break
    else:
        for idx, name, _ in devices:
            if input_str.lower() in name.lower():
                target_idx = idx
                dev_name = f"'{name}' (Index #{idx})"
                break

    if target_idx is None:
        print("\n" + "!" * 80)
        print(f"[CRITICAL ERROR] Invalid AVFoundation camera input: '{input_str}'")
        print("!" * 80)
        print("Run the device list helper to view valid connected webcams:")
        print("  python scripts/simulate_camera.py --list-devices\n")
        raise RuntimeError(f"Could not resolve camera index for '{input_str}'")

    description = f"macOS AVFoundation Webcam {dev_name}"
    print(f"[SIM] Using FFmpeg executable at '{ffmpeg_bin}'")

    # Command uses AVFoundation input with framerate 30, video device index, no audio
    # piped directly to the existing RTSP publish logic
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "avfoundation",
        "-framerate", "30",
        "-video_size", "1280x720",
        "-i", f"{target_idx}:none",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-rtsp_transport", "tcp",
        "-f", "rtsp",
        rtsp_url
    ]

    while True:
        print(f"[SIM] Launching FFmpeg pipeline: {description} -> '{rtsp_url}'")
        proc = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )

        time.sleep(1.5)
        if proc.poll() is not None:
            err_output = proc.stderr.read() if proc.stderr else ""
            print(f"[SIM] FFmpeg failed or disconnected. Retrying in 2s... Error: {err_output[-200:] if err_output else 'none'}")
            time.sleep(2)
            continue

        print(f"[SIM] Successfully acquired stream from {description}")

        last_reported_frame = 0
        frame_pattern = re.compile(r"frame=\s*(\d+)")
        try:
            while proc.poll() is None:
                line = proc.stderr.readline()
                if not line:
                    time.sleep(0.05)
                    continue
                m = frame_pattern.search(line)
                if m:
                    frame_count = int(m.group(1))
                    if frame_count >= last_reported_frame + 30:
                        last_reported_frame = frame_count
                        print(f"[SIM] Published {frame_count} live frames from {description} to '{rtsp_url}'", flush=True)
            print(f"[SIM] Stream disconnected (exit code {proc.poll()}). Reconnecting in 2s...", flush=True)
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n[SIM] Stopping live camera stream...", flush=True)
            break
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()

def stream_camera(input_str: str, stream_name: str, rtsp_url: str):
    """Main streaming engine connecting capture source to MediaMTX RTSP server."""
    # On macOS, if not a video file, use direct AVFoundation capture
    if platform.system() == "Darwin" and not os.path.isfile(input_str):
        stream_camera_mac(input_str, stream_name, rtsp_url)
        return

    # First, acquire and validate capture source (Windows or video file)
    cap, is_file, description = get_webcam_capture(input_str)
    
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
    fps = 15

    ffmpeg_bin = find_ffmpeg_executable()
    
    if ffmpeg_bin:
        print(f"[SIM] Using FFmpeg executable at '{ffmpeg_bin}'")
        # Pipe OpenCV captured frames directly into FFmpeg stdin
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{width}x{height}",
            "-pix_fmt", "bgr24",
            "-r", str(fps),
            "-i", "-",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-rtsp_transport", "tcp",
            "-f", "rtsp",
            rtsp_url
        ]
        
        print(f"[SIM] Launching FFmpeg pipeline: {description} -> '{rtsp_url}'")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        
        frame_count = 0
        try:
            while proc.poll() is None:
                ret, frame = cap.read()
                if not ret or frame is None:
                    if is_file:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        time.sleep(0.01)
                        continue

                if (frame.shape[1], frame.shape[0]) != (width, height):
                    frame = cv2.resize(frame, (width, height))

                try:
                    proc.stdin.write(frame.tobytes())
                    proc.stdin.flush()
                except (IOError, ValueError):
                    break

                frame_count += 1
                if frame_count % 30 == 0:
                    print(f"[SIM] Published {frame_count} live frames from {description} to '{rtsp_url}'", flush=True)
                time.sleep(1.0 / fps)
        except KeyboardInterrupt:
            print("\n[SIM] Stopping live camera stream...", flush=True)
        finally:
            cap.release()
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
    else:
        # Fallback to OpenCV VideoWriter
        print(f"[SIM] FFmpeg not found on PATH. Attempting OpenCV VideoWriter to '{rtsp_url}'...")
        out = cv2.VideoWriter(rtsp_url, cv2.CAP_FFMPEG, 0, fps, (width, height))
        if not out.isOpened():
            cap.release()
            print("\n" + "!" * 80)
            print("[CRITICAL ERROR] Unable to open OpenCV RTSP VideoWriter.")
            print("!" * 80)
            print("OpenCV on Windows requires FFmpeg to publish RTSP streams.")
            print("Please install FFmpeg or run: winget install Gyan.FFmpeg\n")
            raise RuntimeError("RTSP stream output failed — FFmpeg required.")

        frame_count = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret or frame is None:
                    if is_file:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        time.sleep(0.01)
                        continue

                if (frame.shape[1], frame.shape[0]) != (width, height):
                    frame = cv2.resize(frame, (width, height))

                out.write(frame)
                frame_count += 1
                if frame_count % 30 == 0:
                    print(f"[SIM] Published {frame_count} live frames to '{rtsp_url}'", flush=True)
                time.sleep(1.0 / fps)
        except KeyboardInterrupt:
            print("\n[SIM] Stopping camera stream...", flush=True)
        finally:
            cap.release()
            if out:
                out.release()

def main():
    parser = argparse.ArgumentParser(description="IBVAP Real-time RTSP Camera Simulator & Webcam Publisher")
    parser.add_argument("--input", default="0", help="Webcam index (0), DirectShow device name ('USB2.0 HD UVC WebCam'), or video file path")
    parser.add_argument("--stream-name", default="cam1", help="MediaMTX stream name (e.g. cam1)")
    parser.add_argument("--mediamtx-url", default="rtsp://localhost:8554", help="MediaMTX RTSP base URL")
    parser.add_argument("--list-devices", action="store_true", help="List available camera devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        list_available_devices()
        sys.exit(0)

    rtsp_url = f"{args.mediamtx_url.rstrip('/')}/{args.stream_name}"
    stream_camera(args.input, args.stream_name, rtsp_url)

if __name__ == "__main__":
    main()

