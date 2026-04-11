"""
Spot Extractor Tool
从 ND2/TIFF 原始数据中提取高斯光斑及其时间序列信息
整合最大投影、光斑检测、原始视频提取和强度曲线计算功能
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
from pathlib import Path
from PIL import Image, ImageTk
import json
import csv


# ============== 图像处理函数 ==============

def apply_median_filter(image: np.ndarray, size: int = 2) -> np.ndarray:
    """
    应用中值滤波去噪

    Args:
        image: 2D 输入图像
        size: 滤波器大小 (像素)

    Returns:
        滤波后的图像
    """
    from skimage.filters import median
    from skimage.morphology import disk

    if size <= 0:
        return image

    return median(image, disk(size))


def detect_spots(image: np.ndarray, min_sigma: float = 3.0, max_sigma: float = 5.0,
                 num_sigma: int = 3, threshold: float = 0.002) -> list:
    """
    使用 Laplacian of Gaussian (LoG) 检测图像中的高斯光斑

    Args:
        image: 2D 输入图像 (已经过预处理)
        min_sigma: 最小高斯 sigma 值
        max_sigma: 最大高斯 sigma 值
        num_sigma: sigma 采样数量
        threshold: 检测阈值 (相对于图像最大值)

    Returns:
        list of dict: 每个 dict 包含 x, y, radii, intensity
    """
    from skimage.feature import blob_log

    if image.ndim != 2:
        raise ValueError("Image must be 2D")

    img_float = image.astype(np.float64)

    # 归一化到 0-1 范围
    img_min = img_float.min()
    img_max = img_float.max()
    if img_max > img_min:
        img_norm = (img_float - img_min) / (img_max - img_min)
    else:
        img_norm = np.zeros_like(img_float)

    # 使用 blob_log 检测
    blobs = blob_log(
        img_norm,
        min_sigma=min_sigma,
        max_sigma=max_sigma,
        num_sigma=num_sigma,
        threshold=threshold,
        overlap=0.5
    )

    if len(blobs) == 0:
        return []

    spots = []
    for i, blob in enumerate(blobs):
        y, x, sigma = blob
        radii = sigma * np.sqrt(2)

        ix, iy = int(round(x)), int(round(y))
        if 0 <= iy < image.shape[0] and 0 <= ix < image.shape[1]:
            intensity = float(img_float[iy, ix])
        else:
            intensity = 0.0

        spots.append({
            'id': i,
            'x': float(x),
            'y': float(y),
            'radii': float(radii),
            'intensity': intensity
        })

    return spots


def filter_spots_by_boundary(spots: list, image_shape: tuple, box_size: int) -> list:
    """
    过滤掉距离图像边界太近的 spots

    Args:
        spots: spot 列表
        image_shape: 图像形状 (height, width)
        box_size: 用户设置的方框大小

    Returns:
        过滤后的 spot 列表
    """
    if not spots:
        return []

    height, width = image_shape[:2]
    half_box = box_size / 2

    filtered = []
    new_id = 0

    for spot in spots:
        x, y = spot['x'], spot['y']
        dist_left = x
        dist_right = width - 1 - x
        dist_top = y
        dist_bottom = height - 1 - y
        min_dist = min(dist_left, dist_right, dist_top, dist_bottom)

        if min_dist >= half_box:
            spot['id'] = new_id
            filtered.append(spot)
            new_id += 1

    return filtered


def save_tiff(data: np.ndarray, output_path: Path):
    """
    保存为 16-bit TIFF 文件

    Args:
        data: 输入数据
        output_path: 输出路径
    """
    import tifffile

    # 归一化到 16-bit 范围
    if data.dtype != np.uint16:
        data = data.astype(np.float64)
        data_min = data.min()
        data_max = data.max()
        if data_max > data_min:
            data = (data - data_min) / (data_max - data_min) * 65535
        data = data.astype(np.uint16)

    tifffile.imwrite(output_path, data)


def extract_spot_video_worker(spot_id: int, x: int, y: int, channel_data: np.ndarray,
                              output_dir: str, box_size: int, camera_offset: float,
                              radii: float) -> tuple:
    """
    提取单个 spot 的原始视频和强度曲线（模块级函数，用于多进程）

    Args:
        spot_id: spot ID
        x: x 坐标
        y: y 坐标
        channel_data: 通道数据 (TZYX 或 TYX)
        output_dir: 输出目录字符串
        box_size: 方框大小
        camera_offset: camera offset 值
        radii: spot 半径 (用于圆形强度计算)

    Returns:
        (spot_id, video_path, csv_path) 或 (spot_id, None, None) 如果失败
    """
    try:
        output_dir = Path(output_dir)
        half_box = box_size // 2

        # 视频截取区域 (方框)
        y_start = max(0, y - half_box)
        y_end = y_start + box_size
        x_start = max(0, x - half_box)
        x_end = x_start + box_size

        # 预计算圆形 mask (用于强度计算)
        half_r = int(np.ceil(radii)) + 1
        mask_h = 2 * half_r + 1
        yy, xx = np.ogrid[:mask_h, :mask_h]
        circular_mask = (xx - half_r)**2 + (yy - half_r)**2 <= radii**2

        n_frames = channel_data.shape[0]

        # 存储每一帧的 ROI 和强度
        roi_stack = []
        intensities = []

        for t in range(n_frames):
            frame = channel_data[t]

            # 如果是 3D (Z stack)，取最大投影
            if frame.ndim == 3:
                frame = np.max(frame, axis=0)

            # 截取视频 ROI (方框)
            roi = frame[y_start:y_end, x_start:x_end]
            roi_stack.append(roi)

            # 计算强度 (圆形 mask 内像素减去 offset 后求均值)
            cy_start = y - half_r
            cy_end = y + half_r + 1
            cx_start = x - half_r
            cx_end = x + half_r + 1
            circle_region = frame[cy_start:cy_end, cx_start:cx_end]

            if circular_mask.sum() > 0 and circle_region.shape == (mask_h, mask_h):
                intensity = np.mean(circle_region[circular_mask].astype(np.float64) - camera_offset)
            else:
                intensity = 0.0
            intensities.append(intensity)

        # 保存视频为 TIFF stack
        video_array = np.array(roi_stack)
        video_path = output_dir / f"{spot_id + 1}.tif"
        save_tiff(video_array, video_path)

        # 保存强度曲线为 CSV
        csv_path = output_dir / f"{spot_id + 1}.csv"
        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['frame', 'intensity'])
            for t, intensity in enumerate(intensities):
                writer.writerow([t, intensity])

        return (spot_id, str(video_path), str(csv_path))

    except Exception as e:
        print(f"提取 spot {spot_id} 失败: {e}")
        return (spot_id, None, None)


# ============== 图像查看器 ==============

class ImageViewer:
    """高性能图像查看器 (tkinter Canvas + Pillow)"""

    def __init__(self, parent, bg_color='#2b2b2b'):
        self.parent = parent

        # 创建 Canvas
        self.canvas = tk.Canvas(parent, bg=bg_color, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # 图像数据
        self.image_array = None
        self.pil_image = None
        self.tk_image = None

        # 显示参数
        self.zoom_level = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 20.0

        # 平移偏移
        self.offset_x = 0
        self.offset_y = 0

        # 拖拽状态
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_offset_x = 0
        self.drag_offset_y = 0
        self.is_dragging = False

        # Spots 叠加
        self.spots = []
        self.show_spots = True
        self.box_size = 7
        self.spot_items = []

        # 对比度
        self.vmin = 50
        self.vmax = 200

        # 绑定事件
        self.canvas.bind('<Configure>', self.on_resize)
        self.canvas.bind('<MouseWheel>', self.on_mousewheel)
        self.canvas.bind('<Button-4>', self.on_mousewheel)
        self.canvas.bind('<Button-5>', self.on_mousewheel)
        self.canvas.bind('<ButtonPress-3>', self.on_drag_start)
        self.canvas.bind('<B3-Motion>', self.on_drag_move)
        self.canvas.bind('<ButtonRelease-3>', self.on_drag_end)

    def set_image(self, image_array: np.ndarray, vmin=None, vmax=None):
        """设置图像数据"""
        self.image_array = image_array

        if vmin is not None:
            self.vmin = vmin
        if vmax is not None:
            self.vmax = vmax

        self.zoom_level = 1.0
        self.offset_x = 0
        self.offset_y = 0

        self.fit_to_window()

    def set_contrast(self, vmin, vmax):
        """设置对比度"""
        self.vmin = vmin
        self.vmax = vmax
        self.update_display()

    def set_spots(self, spots: list, box_size: int = 7, show: bool = True):
        """设置 spots 数据"""
        self.spots = spots
        self.box_size = box_size
        self.show_spots = show
        self._update_spot_overlays()

    def fit_to_window(self):
        """适配窗口大小"""
        if self.image_array is None:
            return

        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()

        if canvas_w <= 1 or canvas_h <= 1:
            self.parent.after(100, self.fit_to_window)
            return

        img_h, img_w = self.image_array.shape[:2]

        scale_x = canvas_w / img_w
        scale_y = canvas_h / img_h
        self.zoom_level = min(scale_x, scale_y)

        self.offset_x = (canvas_w - img_w * self.zoom_level) / 2
        self.offset_y = (canvas_h - img_h * self.zoom_level) / 2

        self.update_display()

    def update_display(self):
        """更新显示 (图像部分)"""
        if self.image_array is None:
            return

        img_display = self._apply_contrast(self.image_array)

        img_h, img_w = img_display.shape[:2]
        display_w = int(img_w * self.zoom_level)
        display_h = int(img_h * self.zoom_level)

        if display_w <= 0 or display_h <= 0:
            return

        pil_img = Image.fromarray(img_display)
        pil_img = pil_img.resize((display_w, display_h), Image.Resampling.NEAREST)

        self.tk_image = ImageTk.PhotoImage(pil_img)

        self.canvas.delete('image')
        self.canvas.create_image(self.offset_x, self.offset_y, anchor=tk.NW,
                                  image=self.tk_image, tags='image')

        self._update_spot_overlays()

    def _apply_contrast(self, image: np.ndarray) -> np.ndarray:
        """应用对比度调整"""
        img = image.astype(np.float64)
        img = np.clip(img, self.vmin, self.vmax)
        img = (img - self.vmin) / (self.vmax - self.vmin) * 255
        img = img.astype(np.uint8)
        return img

    def _update_spot_overlays(self):
        """更新 spot 覆盖层"""
        self.canvas.delete('spot')

        if not self.show_spots or not self.spots:
            return

        for spot in self.spots:
            screen_x = spot['x'] * self.zoom_level + self.offset_x
            screen_y = spot['y'] * self.zoom_level + self.offset_y
            radii = spot.get('radii', 2.0)
            r = radii * self.zoom_level

            # 红色虚线圆
            self.canvas.create_oval(
                screen_x - r, screen_y - r,
                screen_x + r, screen_y + r,
                outline='red', width=1, dash=(3, 3),
                tags='spot'
            )

            # 绿色方框
            half_box = (self.box_size * self.zoom_level) / 2
            self.canvas.create_rectangle(
                screen_x - half_box, screen_y - half_box,
                screen_x + half_box, screen_y + half_box,
                outline='#00ff00', width=1,
                tags='spot'
            )

        self.canvas.tag_raise('spot')

    def on_resize(self, event):
        """窗口大小改变"""
        if self.image_array is not None:
            self.fit_to_window()

    def on_mousewheel(self, event):
        """滚轮缩放"""
        if self.image_array is None:
            return

        mouse_x = event.x
        mouse_y = event.y

        img_x = (mouse_x - self.offset_x) / self.zoom_level
        img_y = (mouse_y - self.offset_y) / self.zoom_level

        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            factor = 1.1
        else:
            factor = 0.9

        new_zoom = self.zoom_level * factor
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        self.offset_x = mouse_x - img_x * new_zoom
        self.offset_y = mouse_y - img_y * new_zoom
        self.zoom_level = new_zoom

        self._update_image_only()
        self._update_spot_overlays()

    def _update_image_only(self):
        """仅更新图像"""
        if self.image_array is None:
            return

        img_display = self._apply_contrast(self.image_array)

        img_h, img_w = img_display.shape[:2]
        display_w = int(img_w * self.zoom_level)
        display_h = int(img_h * self.zoom_level)

        if display_w <= 0 or display_h <= 0:
            return

        pil_img = Image.fromarray(img_display)
        pil_img = pil_img.resize((display_w, display_h), Image.Resampling.NEAREST)

        self.tk_image = ImageTk.PhotoImage(pil_img)

        self.canvas.delete('image')
        self.canvas.create_image(self.offset_x, self.offset_y, anchor=tk.NW,
                                  image=self.tk_image, tags='image')

    def on_drag_start(self, event):
        """开始拖拽"""
        self.is_dragging = True
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.drag_offset_x = self.offset_x
        self.drag_offset_y = self.offset_y
        self.canvas.config(cursor='fleur')

    def on_drag_move(self, event):
        """拖拽中"""
        if not self.is_dragging:
            return

        dx = event.x - self.drag_start_x
        dy = event.y - self.drag_start_y

        self.offset_x = self.drag_offset_x + dx
        self.offset_y = self.drag_offset_y + dy

        self._update_image_only()
        self._update_spot_overlays()

    def on_drag_end(self, event):
        """结束拖拽"""
        self.is_dragging = False
        self.canvas.config(cursor='')


# ============== 主应用程序 ==============

class SpotExtractorApp:
    """Spot Extractor 应用程序"""

    def __init__(self, root):
        self.root = root
        self.root.title("Spot Extractor - 单分子光斑提取工具")
        self.root.geometry("1500x1100")

        # 图像数据
        self.image_path = None
        self.image_format = None  # 'nd2' 或 'tif'
        self.nd2_image = None  # AICSImage 对象 (ND2)
        self.tif_data = None  # numpy array (TIFF xyt)
        self.max_projections = {}  # {channel_index: max_proj_array}
        self.max_proj_files = {}  # {channel_index: filepath}
        self.n_channels = 0
        self.n_frames = 0
        self.channel_names = []

        # 当前状态
        self.current_channel = 0
        self.current_max_proj = None
        self.processed_image = None
        self.current_spots = []

        # 预处理参数
        self.median_size = tk.IntVar(value=1)

        # 对比度参数
        self.vmin = tk.DoubleVar(value=80)
        self.vmax = tk.DoubleVar(value=200)

        # blob_log 检测参数
        self.min_sigma = tk.DoubleVar(value=3.0)
        self.max_sigma = tk.DoubleVar(value=5.0)
        self.num_sigma = tk.IntVar(value=3)
        self.threshold = tk.DoubleVar(value=0.03)

        # 显示和提取参数
        self.box_size = tk.IntVar(value=7)
        self.camera_offset = tk.DoubleVar(value=0)

        # 显示状态
        self.show_spots_var = tk.BooleanVar(value=True)

        self.setup_ui()

    def setup_ui(self):
        """设置用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 左侧控制面板容器
        control_container = ttk.Frame(main_frame, width=350)
        control_container.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        control_container.pack_propagate(False)  # 固定宽度

        # Canvas 和滚动条
        control_canvas = tk.Canvas(control_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(control_container, orient=tk.VERTICAL, command=control_canvas.yview)
        self.control_frame = ttk.Frame(control_canvas)

        # 绑定配置事件，更新滚动区域和窗口宽度
        def configure_scroll_region(e):
            control_canvas.configure(scrollregion=control_canvas.bbox("all"))
            # 让内部 frame 宽度自适应 canvas 宽度
            canvas_width = control_canvas.winfo_width()
            control_canvas.itemconfig(canvas_window, width=canvas_width)

        self.control_frame.bind("<Configure>", configure_scroll_region)

        # 创建窗口并保存引用
        canvas_window = control_canvas.create_window((0, 0), window=self.control_frame, anchor=tk.NW)

        # 当 canvas 大小改变时，更新内部窗口宽度
        def configure_canvas_width(e):
            canvas_width = control_canvas.winfo_width()
            control_canvas.itemconfig(canvas_window, width=canvas_width)

        control_canvas.bind("<Configure>", configure_canvas_width)

        control_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        control_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # === 文件操作 ===
        file_frame = ttk.LabelFrame(self.control_frame, text="图像文件", padding=5)
        file_frame.pack(fill=tk.X, pady=5, padx=2)

        ttk.Button(file_frame, text="选择文件", command=self.select_file).pack(fill=tk.X, pady=2)
        self.file_label = ttk.Label(file_frame, text="未加载文件")
        self.file_label.pack(pady=2, fill=tk.X)

        # === 通道选择 ===
        channel_frame = ttk.LabelFrame(self.control_frame, text="通道选择", padding=5)
        channel_frame.pack(fill=tk.X, pady=5, padx=2)

        self.channel_var = tk.StringVar()
        self.channel_combo = ttk.Combobox(channel_frame, textvariable=self.channel_var,
                                          state='readonly', width=20)
        self.channel_combo.pack(fill=tk.X, pady=2)
        self.channel_combo.bind('<<ComboboxSelected>>', self.on_channel_change)

        self.frame_label = ttk.Label(channel_frame, text="帧数: -")
        self.frame_label.pack(pady=2)

        # === 最大投影 ===
        proj_frame = ttk.LabelFrame(self.control_frame, text="最大投影", padding=5)
        proj_frame.pack(fill=tk.X, pady=5, padx=2)

        ttk.Button(proj_frame, text="生成最大投影", command=self.generate_max_projection).pack(fill=tk.X, pady=2)
        self.proj_status = ttk.Label(proj_frame, text="状态: 未生成", foreground='gray')
        self.proj_status.pack(pady=2)

        # === 对比度 ===
        contrast_frame = ttk.LabelFrame(self.control_frame, text="对比度", padding=5)
        contrast_frame.pack(fill=tk.X, pady=5, padx=2)

        vmin_frame = ttk.Frame(contrast_frame)
        vmin_frame.pack(fill=tk.X)
        ttk.Label(vmin_frame, text="vmin:").pack(side=tk.LEFT)
        ttk.Entry(vmin_frame, textvariable=self.vmin, width=8).pack(side=tk.RIGHT)

        vmax_frame = ttk.Frame(contrast_frame)
        vmax_frame.pack(fill=tk.X)
        ttk.Label(vmax_frame, text="vmax:").pack(side=tk.LEFT)
        ttk.Entry(vmax_frame, textvariable=self.vmax, width=8).pack(side=tk.RIGHT)

        ttk.Button(contrast_frame, text="应用对比度", command=self.apply_contrast).pack(fill=tk.X, pady=5)

        # === Spot 检测 ===
        detect_frame = ttk.LabelFrame(self.control_frame, text="Spot 检测", padding=5)
        detect_frame.pack(fill=tk.X, pady=5, padx=2)

        ttk.Label(detect_frame, text="── 预处理 ──", foreground='gray').pack()

        median_frame = ttk.Frame(detect_frame)
        median_frame.pack(fill=tk.X)
        ttk.Label(median_frame, text="Median 半径:").pack(side=tk.LEFT)
        ttk.Entry(median_frame, textvariable=self.median_size, width=8).pack(side=tk.RIGHT)

        ttk.Button(detect_frame, text="应用平滑", command=self.apply_preprocessing).pack(fill=tk.X, pady=2)

        ttk.Label(detect_frame, text="── blob_log 参数 ──", foreground='gray').pack(pady=(5, 0))

        for label, var in [("Min Sigma:", self.min_sigma), ("Max Sigma:", self.max_sigma),
                           ("Num Sigma:", self.num_sigma), ("Threshold:", self.threshold)]:
            frame = ttk.Frame(detect_frame)
            frame.pack(fill=tk.X)
            ttk.Label(frame, text=label).pack(side=tk.LEFT)
            ttk.Entry(frame, textvariable=var, width=8).pack(side=tk.RIGHT)

        ttk.Button(detect_frame, text="检测当前通道", command=self.find_spots_current).pack(fill=tk.X, pady=5)

        # === 显示选项 ===
        display_frame = ttk.LabelFrame(self.control_frame, text="显示选项", padding=5)
        display_frame.pack(fill=tk.X, pady=5, padx=2)

        ttk.Checkbutton(display_frame, text="显示 Spot 标记",
                        variable=self.show_spots_var,
                        command=self.update_display).pack(anchor=tk.W)

        box_frame = ttk.Frame(display_frame)
        box_frame.pack(fill=tk.X, pady=2)
        ttk.Label(box_frame, text="Box Size:").pack(side=tk.LEFT)
        ttk.Entry(box_frame, textvariable=self.box_size, width=8).pack(side=tk.RIGHT)
        ttk.Button(box_frame, text="应用", command=self.update_display).pack(side=tk.RIGHT, padx=2)

        hint_label = ttk.Label(display_frame, text="滚轮: 缩放 | 右键: 平移\n红圆: 检测半径 | 绿框: Box",
                               foreground='gray')
        hint_label.pack(anchor=tk.W, pady=5)

        # === 提取参数 ===
        extract_frame = ttk.LabelFrame(self.control_frame, text="提取参数", padding=5)
        extract_frame.pack(fill=tk.X, pady=5, padx=2)

        offset_frame = ttk.Frame(extract_frame)
        offset_frame.pack(fill=tk.X)
        ttk.Label(offset_frame, text="Camera Offset:").pack(side=tk.LEFT)
        ttk.Entry(offset_frame, textvariable=self.camera_offset, width=8).pack(side=tk.RIGHT)

        # === 保存结果 ===
        save_frame = ttk.LabelFrame(self.control_frame, text="保存结果", padding=5)
        save_frame.pack(fill=tk.X, pady=5, padx=2)

        ttk.Button(save_frame, text="保存检测结果 (JSON)",
                   command=self.save_current_json).pack(fill=tk.X, pady=2)
        ttk.Button(save_frame, text="提取所有 Spot 视频",
                   command=self.extract_all_spots).pack(fill=tk.X, pady=2)
        ttk.Button(save_frame, text="一键处理 (检测+提取)",
                   command=self.process_all).pack(fill=tk.X, pady=2)

        # 统计信息
        self.stats_label = ttk.Label(self.control_frame, text="Spots: 0")
        self.stats_label.pack(pady=5)

        # === 右侧图像显示区域 ===
        image_frame = ttk.LabelFrame(main_frame, text="图像预览", padding=5)
        image_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.viewer = ImageViewer(image_frame)

        # === 状态栏 ===
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_label = ttk.Label(status_frame, text="就绪 - 请选择 ND2/TIFF 文件", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.pack(fill=tk.X, padx=5, pady=2)

    def select_file(self):
        """选择图像文件 (ND2 或 TIFF)"""
        filepath = filedialog.askopenfilename(
            title="选择图像文件",
            filetypes=[
                ("ND2 文件", "*.nd2"),
                ("TIFF 文件", "*.tif *.tiff"),
                ("所有文件", "*.*")
            ]
        )

        if filepath:
            ext = Path(filepath).suffix.lower()
            if ext == '.nd2':
                self.load_nd2_file(filepath)
            elif ext in ('.tif', '.tiff'):
                self.load_tif_file(filepath)
            else:
                messagebox.showwarning("警告", f"不支持的文件格式: {ext}")

    def load_nd2_file(self, filepath: str):
        """加载 ND2 文件"""
        try:
            from aicsimageio import AICSImage

            self.status_label.config(text="正在加载 ND2 文件...")
            self.root.update()

            self.image_path = Path(filepath)
            self.image_format = 'nd2'
            self.nd2_image = AICSImage(filepath)
            self.tif_data = None

            # 获取维度信息
            dims_order = self.nd2_image.dims.order
            self.n_channels = self.nd2_image.dims.C if 'C' in dims_order else 1
            self.n_frames = self.nd2_image.dims.T if 'T' in dims_order else 1

            # 生成通道名称
            self.channel_names = [f"通道 {i + 1}" for i in range(self.n_channels)]

            # 更新通道下拉菜单
            self.channel_combo['values'] = self.channel_names
            if self.channel_names:
                self.channel_combo.current(0)
                self.current_channel = 0

            # 更新文件信息
            self.file_label.config(text=f"{self.image_path.name}")
            self.frame_label.config(text=f"帧数: {self.n_frames}")

            # 重置状态
            self.max_projections.clear()
            self.max_proj_files.clear()
            self.current_max_proj = None
            self.processed_image = None
            self.current_spots = []
            self.proj_status.config(text="状态: 未生成")

            # 清空右侧图像区
            self.clear_image_viewer()

            self.status_label.config(text=f"已加载: {self.image_path.name} | {self.n_channels} 通道, {self.n_frames} 帧")

        except Exception as e:
            messagebox.showerror("错误", f"无法加载 ND2 文件: {e}")
            self.status_label.config(text="加载失败")

    def load_tif_file(self, filepath: str):
        """加载多页 TIFF 文件 (xyt 格式)"""
        try:
            import tifffile

            self.status_label.config(text="正在加载 TIFF 文件...")
            self.root.update()

            self.image_path = Path(filepath)
            self.image_format = 'tif'
            self.nd2_image = None
            self.tif_data = tifffile.imread(filepath)

            # 验证维度: 期望 (T, Y, X) 或 (Y, X)
            if self.tif_data.ndim == 2:
                self.tif_data = self.tif_data[np.newaxis, ...]
            elif self.tif_data.ndim != 3:
                messagebox.showerror("错误",
                    f"不支持的 TIFF 维度: {self.tif_data.ndim}D\n"
                    f"仅支持 xyt 格式 (3D: T×Y×X)")
                self.status_label.config(text="加载失败")
                return

            self.n_frames = self.tif_data.shape[0]
            self.n_channels = 1  # xyt TIFF 仅支持单通道
            self.channel_names = ["通道 1"]

            # 设置 camera offset 为全局最小值
            self._update_camera_offset_default(self.tif_data)

            # 更新通道下拉菜单
            self.channel_combo['values'] = self.channel_names
            self.channel_combo.current(0)
            self.current_channel = 0

            # 更新文件信息
            self.file_label.config(text=f"{self.image_path.name}")
            self.frame_label.config(text=f"帧数: {self.n_frames}")

            # 重置状态
            self.max_projections.clear()
            self.max_proj_files.clear()
            self.current_max_proj = None
            self.processed_image = None
            self.current_spots = []
            self.proj_status.config(text="状态: 未生成")

            # 清空右侧图像区
            self.clear_image_viewer()

            self.status_label.config(
                text=f"已加载: {self.image_path.name} | "
                     f"{self.n_frames} 帧, {self.tif_data.shape[1]}×{self.tif_data.shape[2]}")

        except Exception as e:
            messagebox.showerror("错误", f"无法加载 TIFF 文件: {e}")
            self.status_label.config(text="加载失败")

    def get_channel_data(self, channel_index: int) -> np.ndarray:
        """获取指定通道的数据 (TZYX 或 TYX)"""
        if self.image_format == 'nd2':
            return self.nd2_image.get_image_data("TZYX", C=channel_index)
        elif self.image_format == 'tif':
            return self.tif_data  # (T, Y, X)
        else:
            raise ValueError(f"未知图像格式: {self.image_format}")

    def _update_camera_offset_default(self, data: np.ndarray):
        """根据数据最小值更新 camera offset 默认值"""
        data_min = float(np.min(data))
        self.camera_offset.set(round(data_min, 1))

    def _auto_set_contrast(self, image: np.ndarray):
        """根据图像百分位数自动设定对比度"""
        vmin_auto = float(np.percentile(image, 1))
        vmax_auto = float(np.percentile(image, 99))
        if vmax_auto <= vmin_auto:
            vmax_auto = vmin_auto + 1
        self.vmin.set(round(vmin_auto, 1))
        self.vmax.set(round(vmax_auto, 1))

    def clear_image_viewer(self):
        """清空右侧图像查看器"""
        # 清空图像
        self.viewer.image_array = None
        self.viewer.spots = []
        self.viewer.canvas.delete('image')
        self.viewer.canvas.delete('spot')

        # 重置统计
        self.stats_label.config(text="Spots: 0")

    def on_channel_change(self, event=None):
        """通道切换"""
        if not self.channel_names:
            return

        idx = self.channel_combo.current()
        if idx < 0:
            return

        self.current_channel = idx
        self.status_label.config(text=f"切换到 {self.channel_names[idx]}")

        # 如果已有该通道的最大投影，直接显示
        if idx in self.max_projections:
            self.current_max_proj = self.max_projections[idx]
            self.processed_image = None
            self.current_spots = []
            self.apply_preprocessing()
            self.update_display()
        else:
            # 清空显示
            self.current_max_proj = None
            self.processed_image = None
            self.current_spots = []
            self.viewer.set_image(np.zeros((100, 100), dtype=np.uint16))
            self.stats_label.config(text="Spots: 0")

    def generate_max_projection(self):
        """生成当前通道的最大投影"""
        if self.image_path is None:
            messagebox.showwarning("警告", "请先加载图像文件")
            return

        try:
            self.root.config(cursor='watch')
            self.status_label.config(text="正在生成最大投影...")
            self.root.update()

            ch = self.current_channel

            # 获取该通道的所有时间帧数据
            channel_data = self.get_channel_data(ch)

            # 沿时间轴进行最大投影
            max_proj = np.max(channel_data, axis=0)

            # 如果还有 Z 维度，继续投影
            while max_proj.ndim > 2:
                max_proj = np.max(max_proj, axis=0)

            self.max_projections[ch] = max_proj
            self.current_max_proj = max_proj

            # 根据图像自动设定对比度
            self._auto_set_contrast(max_proj)

            # 更新 camera offset 为当前通道数据最小值
            self._update_camera_offset_default(channel_data)

            # 保存最大投影文件
            output_name = f"{self.image_path.stem}_ch{ch + 1}_max.tif"
            output_path = self.image_path.parent / output_name
            save_tiff(max_proj, output_path)
            self.max_proj_files[ch] = output_path

            self.proj_status.config(text=f"状态: 已保存 {output_name}")

            # 应用预处理并显示
            self.processed_image = None
            self.current_spots = []
            self.apply_preprocessing()
            self.update_display()

            self.root.config(cursor='')
            self.status_label.config(text=f"最大投影已生成: {output_name}")

        except Exception as e:
            self.root.config(cursor='')
            messagebox.showerror("错误", f"生成最大投影失败: {e}")
            self.status_label.config(text="生成失败")

    def apply_contrast(self):
        """应用对比度设置"""
        if self.processed_image is not None:
            self.viewer.set_contrast(self.vmin.get(), self.vmax.get())

    def apply_preprocessing(self):
        """应用预处理 (中值滤波)"""
        if self.current_max_proj is None:
            return

        median_size = self.median_size.get()
        self.processed_image = apply_median_filter(self.current_max_proj, size=median_size)

        # 更新显示
        self.viewer.set_image(
            self.processed_image,
            vmin=self.vmin.get(),
            vmax=self.vmax.get()
        )

    def find_spots_current(self):
        """检测当前通道的 spots"""
        if self.current_max_proj is None:
            messagebox.showwarning("警告", "请先生成最大投影")
            return

        try:
            self.root.config(cursor='watch')
            self.status_label.config(text="正在检测...")
            self.root.update()

            # 使用处理后的图像进行检测
            detect_image = self.processed_image if self.processed_image is not None else self.current_max_proj

            spots = detect_spots(
                detect_image,
                min_sigma=self.min_sigma.get(),
                max_sigma=self.max_sigma.get(),
                num_sigma=self.num_sigma.get(),
                threshold=self.threshold.get()
            )

            # 过滤边界附近的 spots
            box_size = self.box_size.get()
            spots = filter_spots_by_boundary(spots, detect_image.shape, box_size)

            self.current_spots = spots

            self.viewer.set_spots(
                self.current_spots,
                box_size=self.box_size.get(),
                show=self.show_spots_var.get()
            )

            self.root.config(cursor='')
            self.stats_label.config(text=f"Spots: {len(spots)}")
            self.status_label.config(text=f"检测到 {len(spots)} 个 spots")

            messagebox.showinfo("完成", f"检测到 {len(spots)} 个 spots")

        except Exception as e:
            self.root.config(cursor='')
            self.status_label.config(text="检测失败")
            messagebox.showerror("错误", f"检测失败: {e}")

    def update_display(self):
        """更新图像显示"""
        if self.processed_image is not None:
            self.viewer.set_image(
                self.processed_image,
                vmin=self.vmin.get(),
                vmax=self.vmax.get()
            )
            self.viewer.set_spots(
                self.current_spots,
                box_size=self.box_size.get(),
                show=self.show_spots_var.get()
            )
            self.stats_label.config(text=f"Spots: {len(self.current_spots)}")

    def save_current_json(self):
        """保存当前通道的检测结果到 JSON 文件"""
        if not self.current_spots:
            messagebox.showwarning("警告", "当前没有检测数据，请先执行检测")
            return

        if self.image_path is None:
            return

        output_path = self.image_path.parent / f"{self.image_path.stem}_ch{self.current_channel + 1}_spots.json"

        try:
            data = {
                'source_file': self.image_path.name,
                'channel': self.current_channel + 1,
                'image_shape': list(self.current_max_proj.shape) if self.current_max_proj is not None else None,
                'parameters': {
                    'preprocessing': {
                        'median_size': self.median_size.get()
                    },
                    'detection': {
                        'min_sigma': self.min_sigma.get(),
                        'max_sigma': self.max_sigma.get(),
                        'num_sigma': self.num_sigma.get(),
                        'threshold': self.threshold.get()
                    },
                    'display': {
                        'box_size': self.box_size.get()
                    }
                },
                'spots': [
                    {
                        'id': spot['id'],
                        'x': spot['x'],
                        'y': spot['y'],
                        'radii': spot['radii'],
                        'intensity': spot['intensity']
                    }
                    for spot in self.current_spots
                ],
                'spot_count': len(self.current_spots)
            }

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self.status_label.config(text=f"已保存 {len(self.current_spots)} 个 spots 到 {output_path.name}")
            messagebox.showinfo("成功", f"已保存到:\n{output_path}")

        except Exception as e:
            messagebox.showerror("错误", f"保存失败: {e}")

    def extract_spot_video(self, spot: dict, channel_data: np.ndarray, output_dir: Path,
                           box_size: int, camera_offset: float, radii: float) -> tuple:
        """
        提取单个 spot 的原始视频和强度曲线

        Args:
            spot: spot 信息字典
            channel_data: 通道数据 (TZYX 或 TYX)
            output_dir: 输出目录
            box_size: 方框大小
            camera_offset: camera offset 值
            radii: spot 半径 (用于圆形强度计算)

        Returns:
            (video_path, csv_path) 或 (None, None) 如果失败
        """
        try:
            spot_id = spot['id']
            x = int(round(spot['x']))
            y = int(round(spot['y']))

            half_box = box_size // 2

            # 视频截取区域 (方框)
            y_start = max(0, y - half_box)
            y_end = y_start + box_size
            x_start = max(0, x - half_box)
            x_end = x_start + box_size

            # 预计算圆形 mask (用于强度计算)
            half_r = int(np.ceil(radii)) + 1
            mask_h = 2 * half_r + 1
            yy, xx = np.ogrid[:mask_h, :mask_h]
            circular_mask = (xx - half_r)**2 + (yy - half_r)**2 <= radii**2

            n_frames = channel_data.shape[0]

            # 存储每一帧的 ROI 和强度
            roi_stack = []
            intensities = []

            for t in range(n_frames):
                frame = channel_data[t]

                # 如果是 3D (Z stack)，取最大投影
                if frame.ndim == 3:
                    frame = np.max(frame, axis=0)

                # 截取视频 ROI (方框)
                roi = frame[y_start:y_end, x_start:x_end]
                roi_stack.append(roi)

                # 计算强度 (圆形 mask 内像素减去 offset 后求均值)
                cy_start = y - half_r
                cy_end = y + half_r + 1
                cx_start = x - half_r
                cx_end = x + half_r + 1
                circle_region = frame[cy_start:cy_end, cx_start:cx_end]

                if circular_mask.sum() > 0 and circle_region.shape == (mask_h, mask_h):
                    intensity = np.mean(circle_region[circular_mask].astype(np.float64) - camera_offset)
                else:
                    intensity = 0.0
                intensities.append(intensity)

            # 保存视频为 TIFF stack
            video_array = np.array(roi_stack)
            video_path = output_dir / f"{spot_id + 1}.tif"
            save_tiff(video_array, video_path)

            # 保存强度曲线为 CSV
            csv_path = output_dir / f"{spot_id + 1}.csv"
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['frame', 'intensity'])
                for t, intensity in enumerate(intensities):
                    writer.writerow([t, intensity])

            return video_path, csv_path

        except Exception as e:
            print(f"提取 spot {spot['id']} 失败: {e}")
            return None, None

    def extract_all_spots(self):
        """提取所有 spots 的原始视频和强度曲线（顺序处理）"""
        if not self.current_spots:
            messagebox.showwarning("警告", "当前没有检测数据，请先执行检测")
            return

        if self.image_path is None:
            return

        try:
            self.root.config(cursor='watch')
            self.status_label.config(text="正在准备数据...")
            self.root.update()

            # 获取通道数据
            channel_data = self.get_channel_data(self.current_channel)

            # 创建输出目录（包含通道信息）
            output_dir = self.image_path.parent / f"{self.image_path.stem}_ch{self.current_channel + 1}_spots"
            output_dir.mkdir(exist_ok=True)

            n_spots = len(self.current_spots)
            box_size = self.box_size.get()
            camera_offset = self.camera_offset.get()

            video_files = []
            csv_files = []

            # 顺序处理每个 spot
            for i, spot in enumerate(self.current_spots):
                self.status_label.config(text=f"提取 spot {i + 1}/{n_spots}...")
                self.root.update()

                result = extract_spot_video_worker(
                    spot['id'],
                    int(round(spot['x'])),
                    int(round(spot['y'])),
                    channel_data,
                    str(output_dir),
                    box_size,
                    camera_offset,
                    spot['radii']
                )

                _, video_path, csv_path = result
                if video_path:
                    video_files.append(video_path)
                if csv_path:
                    csv_files.append(csv_path)

            self.root.config(cursor='')
            self.status_label.config(text=f"已提取 {len(video_files)} 个 spot 视频到 {output_dir.name}")

            messagebox.showinfo("完成",
                f"提取完成!\n\n"
                f"视频文件: {len(video_files)}\n"
                f"强度曲线: {len(csv_files)}\n"
                f"保存目录: {output_dir}"
            )

        except Exception as e:
            self.root.config(cursor='')
            messagebox.showerror("错误", f"提取失败: {e}")
            self.status_label.config(text="提取失败")

    def process_all(self):
        """一键处理：生成最大投影、检测 spots、提取视频"""
        if self.image_path is None:
            messagebox.showwarning("警告", "请先加载图像文件")
            return

        try:
            self.root.config(cursor='watch')

            # 1. 生成最大投影
            self.status_label.config(text="步骤 1/3: 生成最大投影...")
            self.root.update()
            self.generate_max_projection()

            # 2. 检测 spots
            self.status_label.config(text="步骤 2/3: 检测 spots...")
            self.root.update()
            self.find_spots_current()

            # 3. 保存 JSON
            self.status_label.config(text="步骤 3/3: 保存检测结果...")
            self.root.update()
            self.save_current_json()

            # 4. 提取视频
            if self.current_spots:
                self.extract_all_spots()
            else:
                self.root.config(cursor='')
                messagebox.showinfo("完成", "处理完成，但未检测到 spots")

        except Exception as e:
            self.root.config(cursor='')
            messagebox.showerror("错误", f"处理失败: {e}")
            self.status_label.config(text="处理失败")


def main():
    """主函数"""
    root = tk.Tk()
    app = SpotExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
