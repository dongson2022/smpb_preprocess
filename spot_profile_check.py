"""
Spot Profile Check Tool
检查 spots 目录中的 tif 视频和 csv 强度曲线数据
支持标注和筛选
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
from pathlib import Path
from PIL import Image, ImageTk
import json
import csv
from natsort import natsorted

try:
    import tifffile
except ImportError:
    tifffile = None

try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    from matplotlib.figure import Figure
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


class SpotMovieViewer:
    """Spot Movie 显示器 - 高性能版本"""

    def __init__(self, parent, size=300):
        self.parent = parent
        self.size = size

        # 创建 Canvas (固定大小)
        self.canvas = tk.Canvas(parent, width=size, height=size, bg='#2b2b2b', highlightthickness=0)
        self.canvas.pack()

        # 数据
        self.movie_data = None
        self.current_frame = 0
        self.total_frames = 0

        # 预缓存的 PhotoImage 列表
        self._photo_cache = []

        # 对比度
        self.vmin = 0
        self.vmax = 65535

        # 帧变化回调
        self.on_frame_change = None

    def set_movie(self, movie_data, vmin=None, vmax=None):
        """设置 movie 数据并预处理"""
        self.movie_data = movie_data
        self._photo_cache.clear()

        if movie_data is None:
            self.canvas.delete('all')
            return

        if movie_data.ndim == 2:
            self.movie_data = movie_data[np.newaxis, ...]

        self.total_frames = self.movie_data.shape[0]
        self.current_frame = 0

        if vmin is not None:
            self.vmin = vmin
        if vmax is not None:
            self.vmax = vmax

        # 预处理所有帧为 PhotoImage
        self._precache_frames()
        self._show_frame(0)

    def _precache_frames(self):
        """预处理所有帧为 PhotoImage"""
        self._photo_cache.clear()

        for i in range(self.total_frames):
            frame = self.movie_data[i]
            # 应用对比度
            img = np.clip(frame, self.vmin, self.vmax)
            img = ((img - self.vmin) / (self.vmax - self.vmin) * 255).astype(np.uint8)

            # 缩放到固定大小
            pil_img = Image.fromarray(img)
            pil_img = pil_img.resize((self.size, self.size), Image.Resampling.NEAREST)

            self._photo_cache.append(ImageTk.PhotoImage(pil_img))

    def _show_frame(self, idx):
        """显示指定帧 (无回调)"""
        if not self._photo_cache or idx < 0 or idx >= self.total_frames:
            return

        self.current_frame = idx
        photo = self._photo_cache[idx]

        # 直接替换图像
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        self.canvas.create_text(5, 5, anchor=tk.NW,
                                text=f"{idx + 1}/{self.total_frames}",
                                fill='white', font=('Arial', 9))

    def set_frame(self, idx):
        """设置当前帧 (触发回调)"""
        self._show_frame(idx)
        if self.on_frame_change:
            self.on_frame_change(idx)

    def set_contrast(self, vmin, vmax):
        """设置对比度并刷新"""
        self.vmin = vmin
        self.vmax = vmax
        if self.movie_data is not None:
            self._precache_frames()
            self._show_frame(self.current_frame)


class CurvePlotter:
    """强度曲线绘图器 - Matplotlib 版本"""

    def __init__(self, parent):
        self.parent = parent
        self.data = None
        self.current_frame = 0

        if HAS_MATPLOTLIB:
            # 创建 Figure
            self.fig = Figure(figsize=(6, 4), dpi=100)
            self.ax = self.fig.add_subplot(111)
            self.fig.tight_layout(pad=2)

            # Canvas
            self.canvas = FigureCanvasTkAgg(self.fig, master=parent)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

            # 工具栏
            toolbar_frame = ttk.Frame(parent)
            toolbar_frame.pack(fill=tk.X)
            self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
            self.toolbar.update()

            # 垂直线标记
            self.vline = None
            self.marker_point = None
        else:
            # 回退到简单 Canvas
            self.canvas_widget = tk.Canvas(parent, bg='white', highlightthickness=0)
            self.canvas_widget.pack(fill=tk.BOTH, expand=True)

    def set_data(self, data):
        """设置数据"""
        self.data = data
        if not HAS_MATPLOTLIB:
            return

        self.ax.clear()
        if data is None or len(data) == 0:
            self.canvas.draw()
            return

        # 绘制曲线
        x = np.arange(len(data))
        self.ax.plot(x, data, 'gray', linewidth=1.5)
        self.ax.set_xlabel('Frame')
        self.ax.set_ylabel('Intensity')
        self.ax.grid(True, alpha=0.3)

        # 初始化标记
        self.vline = self.ax.axvline(x=0, color='red', linestyle='--', alpha=0.7)
        self.marker_point, = self.ax.plot([0], [data[0]], 'ro', markersize=6)

        self.fig.tight_layout(pad=2)
        self.canvas.draw()

    def set_frame(self, idx):
        """设置当前帧标记"""
        self.current_frame = idx
        if not HAS_MATPLOTLIB or self.data is None:
            return

        if idx < 0 or idx >= len(self.data):
            return

        # 更新垂直线
        if self.vline:
            self.vline.set_xdata([idx, idx])

        # 更新标记点
        if self.marker_point:
            self.marker_point.set_data([idx], [self.data[idx]])

        self.canvas.draw_idle()

    def reset_zoom(self):
        """重置缩放"""
        if not HAS_MATPLOTLIB:
            return

        self.ax.clear()
        if self.data is not None and len(self.data) > 0:
            x = np.arange(len(self.data))
            self.ax.plot(x, self.data, 'gray', linewidth=1.5)
            self.ax.set_xlabel('Frame')
            self.ax.set_ylabel('Intensity')
            self.ax.grid(True, alpha=0.3)

            self.vline = self.ax.axvline(x=self.current_frame, color='red', linestyle='--', alpha=0.7)
            self.marker_point, = self.ax.plot([self.current_frame], [self.data[self.current_frame]], 'ro', markersize=6)

        self.fig.tight_layout(pad=2)
        self.canvas.draw()

    def zoom_back(self):
        """后退 - matplotlib 工具栏自带后退功能"""
        pass

    def set_xlim(self, start, end):
        """设置 X 轴显示范围，并自适应 Y 轴"""
        if not HAS_MATPLOTLIB or self.data is None:
            return

        if start < 0:
            start = 0
        if end >= len(self.data):
            end = len(self.data) - 1

        if start < end:
            self.ax.set_xlim(start, end)

            # 根据 cutoff 范围内的数据自适应 Y 轴
            region_data = self.data[start:end+1]
            y_min = float(np.min(region_data))
            y_max = float(np.max(region_data))
            margin = max(1, (y_max - y_min) * 0.1)
            self.ax.set_ylim(y_min - margin, y_max + margin)

            self.canvas.draw_idle()


class SpotProfileCheckApp:
    """Spot Profile Check 应用"""

    def __init__(self, root):
        self.root = root
        self.root.title("Spot Profile Check")
        self.root.geometry("1400x820")

        # 数据
        self.spots_dir = None
        self.spot_files = []  # [(spot_id, tif_path, csv_path), ...]
        self.current_spot_idx = 0
        self.current_movie = None
        self.current_csv_data = None

        # 标注
        self.annotations = {}  # spot_id -> {'qualified': '', 'labels': '', 'cutoff_start': '', 'cutoff_end': ''}

        # UI 变量
        self.vmin = tk.DoubleVar(value=80)
        self.vmax = tk.DoubleVar(value=300)
        self.qualified_var = tk.StringVar(value='')
        self.label_var = tk.StringVar()
        self.cutoff_start = tk.StringVar(value='')
        self.cutoff_end = tk.StringVar(value='')

        # 标签列表（从已有标注中动态提取）
        self.labels = []

        self._setup_ui()

    def _setup_ui(self):
        """设置界面"""
        # 主框架
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 使用 grid 布局控制比例
        main.columnconfigure(0, weight=0, minsize=350)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        # === 左侧面板 ===
        left = ttk.Frame(main, width=350)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        left.grid_propagate(False)

        # 目录加载
        dir_frame = ttk.Frame(left)
        dir_frame.pack(fill=tk.X, pady=5)
        ttk.Button(dir_frame, text="打开 spots 目录", command=self._load_directory).pack(side=tk.LEFT, padx=5)
        self.dir_label = ttk.Label(dir_frame, text="未加载")
        self.dir_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(dir_frame, text="导出CSV", command=self._export_csv).pack(side=tk.RIGHT, padx=5)

        # Spot Movie (300x300)
        movie_frame = ttk.LabelFrame(left, text="Spot Movie", padding=5)
        movie_frame.pack(pady=5)

        self.movie_viewer = SpotMovieViewer(movie_frame, size=300)
        self.movie_viewer.on_frame_change = self._on_frame_change

        # 帧导航
        nav = ttk.Frame(movie_frame)
        nav.pack(fill=tk.X, pady=5)
        ttk.Button(nav, text="◀◀", width=3, command=lambda: self._goto_frame(0)).pack(side=tk.LEFT, padx=1)
        ttk.Button(nav, text="◀", width=3, command=self._prev_frame).pack(side=tk.LEFT, padx=1)
        ttk.Button(nav, text="▶", width=3, command=self._next_frame).pack(side=tk.LEFT, padx=1)
        ttk.Button(nav, text="▶▶", width=3, command=self._goto_last).pack(side=tk.LEFT, padx=1)
        self.frame_label = ttk.Label(nav, text="0/0", width=8)
        self.frame_label.pack(side=tk.LEFT, padx=5)

        self.frame_slider = ttk.Scale(movie_frame, from_=0, to=100, orient=tk.HORIZONTAL,
                                       command=lambda v: self._goto_frame(int(float(v))))
        self.frame_slider.pack(fill=tk.X, pady=2)

        # 对比度
        contrast = ttk.LabelFrame(left, text="对比度", padding=5)
        contrast.pack(fill=tk.X, pady=5)
        cf = ttk.Frame(contrast)
        cf.pack(fill=tk.X)
        ttk.Label(cf, text="Min:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(cf, textvariable=self.vmin, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(cf, text="Max:").pack(side=tk.LEFT, padx=2)
        ttk.Entry(cf, textvariable=self.vmax, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(cf, text="应用", command=self._apply_contrast).pack(side=tk.LEFT, padx=5)

        # 标注区域
        anno = ttk.LabelFrame(left, text="数据标注", padding=5)
        anno.pack(fill=tk.BOTH, expand=True, pady=5)

        # Spot 导航
        spot_nav = ttk.Frame(anno)
        spot_nav.pack(fill=tk.X, pady=3)
        ttk.Button(spot_nav, text="◀", width=2, command=self._prev_spot).pack(side=tk.LEFT, padx=2)
        self.spot_label = ttk.Label(spot_nav, text="Spot: 0/0")
        self.spot_label.pack(side=tk.LEFT, padx=5)
        ttk.Button(spot_nav, text="▶", width=2, command=self._next_spot).pack(side=tk.LEFT, padx=2)
        # 标注状态指示
        self.anno_status_label = ttk.Label(spot_nav, text="", font=('Arial', 9, 'bold'))
        self.anno_status_label.pack(side=tk.LEFT, padx=10)

        # ID 跳转
        jump_frame = ttk.Frame(anno)
        jump_frame.pack(fill=tk.X, pady=3)
        self.jump_id_var = tk.StringVar()
        self.jump_id_var.set("跳转到Spot ID")
        jump_entry = ttk.Entry(jump_frame, textvariable=self.jump_id_var, width=20)
        jump_entry.pack(side=tk.LEFT, padx=2)
        jump_entry.bind('<Return>', lambda e: self._jump_to_spot())
        jump_entry.bind('<FocusIn>', lambda e: (self.jump_id_var.set('') if self.jump_id_var.get() == "跳转到Spot ID" else None))
        jump_entry.bind('<FocusOut>', lambda e: (self.jump_id_var.set("跳转到Spot ID") if not self.jump_id_var.get().strip() else None))
        ttk.Button(jump_frame, text="跳转", width=4, command=self._jump_to_spot).pack(side=tk.LEFT, padx=2)

        # 筛选
        filt = ttk.Frame(anno)
        filt.pack(fill=tk.X, pady=3)
        ttk.Label(filt, text="筛选:").pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(filt, text="合格", variable=self.qualified_var,
                        value='qualified', command=self._on_anno).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(filt, text="不合格", variable=self.qualified_var,
                        value='unqualified', command=self._on_anno).pack(side=tk.LEFT, padx=5)

        # 标签 (支持多个，逗号分隔)
        lbl = ttk.Frame(anno)
        lbl.pack(fill=tk.X, pady=3)
        ttk.Label(lbl, text="标签:").pack(side=tk.LEFT, padx=2)
        self.label_combo = ttk.Combobox(lbl, textvariable=self.label_var,
                                          values=self.labels, width=25)
        self.label_combo.pack(side=tk.LEFT, padx=2)
        self.label_combo.bind('<<ComboboxSelected>>', lambda e: self._on_anno())
        self.label_combo.bind('<Return>', lambda e: self._on_anno())
        ttk.Button(lbl, text="+", width=2, command=self._add_label).pack(side=tk.LEFT, padx=2)

        # Cutoff 范围
        cutoff_frame = ttk.Frame(anno)
        cutoff_frame.pack(fill=tk.X, pady=3)
        ttk.Label(cutoff_frame, text="Cutoff:").pack(side=tk.LEFT, padx=2)
        ttk.Label(cutoff_frame, text="Start").pack(side=tk.LEFT, padx=2)
        ttk.Entry(cutoff_frame, textvariable=self.cutoff_start, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(cutoff_frame, text="End").pack(side=tk.LEFT, padx=2)
        ttk.Entry(cutoff_frame, textvariable=self.cutoff_end, width=6).pack(side=tk.LEFT, padx=2)

        cutoff_btn = ttk.Frame(anno)
        cutoff_btn.pack(fill=tk.X, pady=3)
        ttk.Button(cutoff_btn, text="保存", command=self._on_anno).pack(side=tk.LEFT, padx=2)
        ttk.Button(cutoff_btn, text="清除", command=self._clear_cutoff).pack(side=tk.LEFT, padx=2)
        ttk.Button(cutoff_btn, text="重置视图", command=self._reset_view).pack(side=tk.LEFT, padx=2)

        # 统计
        self.stats_label = ttk.Label(anno, text="合格: 0 | 不合格: 0 | 未标记: 0")
        self.stats_label.pack(anchor=tk.W, pady=3)

        # === 右侧曲线区域 ===
        right = ttk.LabelFrame(main, text="强度时间曲线 (来自 CSV)", padding=5)
        right.grid(row=0, column=1, sticky='nsew')

        self.plotter = CurvePlotter(right)

        # 状态栏
        status = ttk.Frame(self.root)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status = ttk.Label(status, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, padx=5, pady=2)

        # 绑定快捷键
        self.root.bind('<q>', lambda e: self._quick_annotate('qualified'))
        self.root.bind('<w>', lambda e: self._quick_annotate('unqualified'))
        self.root.bind('<e>', lambda e: self._quick_annotate(''))
        self.root.bind('<Left>', lambda e: self._prev_spot())
        self.root.bind('<Right>', lambda e: self._next_spot())
        self.root.bind('<space>', lambda e: self._next_unmarked())

    def _load_directory(self):
        """加载 spots 目录"""
        dir_path = filedialog.askdirectory(title="选择 spots 目录")
        if not dir_path:
            return

        try:
            self.spots_dir = Path(dir_path)

            # 查找所有 tif 文件
            tif_files = list(self.spots_dir.glob("*.tif")) + list(self.spots_dir.glob("*.tiff"))

            if not tif_files:
                messagebox.showerror("错误", "目录中未找到 tif 文件")
                return

            # 使用 natsort 排序
            tif_files = natsorted(tif_files, key=lambda p: p.stem)

            # 匹配对应的 csv 文件
            self.spot_files = []
            for tif_path in tif_files:
                spot_id = tif_path.stem
                csv_path = self.spots_dir / f"{spot_id}.csv"
                if csv_path.exists():
                    self.spot_files.append((spot_id, tif_path, csv_path))
                else:
                    # 如果没有对应的 csv，也加入列表（曲线为空）
                    self.spot_files.append((spot_id, tif_path, None))

            if not self.spot_files:
                messagebox.showerror("错误", "未找到有效的 spot 文件对")
                return

            if tifffile is None:
                messagebox.showerror("错误", "请安装 tifffile: pip install tifffile")
                return

            # 更新 UI
            self.dir_label.config(text=f"{self.spots_dir.name} ({len(self.spot_files)} spots)")

            # 加载标注
            self._load_annotations()

            # 加载第一个 spot
            self.current_spot_idx = 0
            self._load_spot()

            self.status.config(text=f"已加载 {len(self.spot_files)} 个 spots")

        except Exception as e:
            messagebox.showerror("错误", f"加载失败: {e}")

    def _load_annotations(self):
        """加载标注"""
        self.annotations.clear()
        self.labels = []  # 重置标签列表
        anno_file = self.spots_dir / "annotations.json"

        if anno_file.exists():
            try:
                with open(anno_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.annotations = data.get('annotations', {})

                # 从已有标注中提取标签（支持逗号分隔的多标签）
                label_set = set()
                for anno in self.annotations.values():
                    labels_str = anno.get('labels', '')
                    if labels_str:
                        for lbl in labels_str.split(','):
                            lbl = lbl.strip()
                            if lbl:
                                label_set.add(lbl)
                self.labels = sorted(list(label_set))

                # 更新下拉框候选列表
                self.label_combo['values'] = self.labels
            except:
                pass

    def _save_annotations(self):
        """保存标注"""
        if not self.spots_dir:
            return

        anno_file = self.spots_dir / "annotations.json"

        # 统计
        qualified_count = sum(1 for a in self.annotations.values() if a.get('qualified') == 'qualified')
        unqualified_count = sum(1 for a in self.annotations.values() if a.get('qualified') == 'unqualified')

        data = {
            'directory': str(self.spots_dir),
            'total_spots': len(self.spot_files),
            'qualified_count': qualified_count,
            'unqualified_count': unqualified_count,
            'annotations': self.annotations
        }

        with open(anno_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load_spot(self):
        """加载当前 spot"""
        if not self.spot_files:
            return

        if self.current_spot_idx >= len(self.spot_files):
            return

        spot_id, tif_path, csv_path = self.spot_files[self.current_spot_idx]

        # 加载 tif
        try:
            self.current_movie = tifffile.imread(str(tif_path))
            # 如果是 3D 数据 (TYX)，直接使用；如果是 2D (YX)，添加维度
            if self.current_movie.ndim == 2:
                self.current_movie = self.current_movie[np.newaxis, ...]
        except Exception as e:
            self.status.config(text=f"加载 tif 失败: {e}")
            return

        # 加载 csv (格式: frame,intensity)
        self.current_csv_data = None
        if csv_path:
            try:
                data = []
                with open(csv_path, 'r', newline='') as f:
                    reader = csv.reader(f)
                    header = next(reader, None)  # 跳过表头
                    for row in reader:
                        if len(row) >= 2:
                            try:
                                val = float(row[1])  # intensity 在第二列
                                data.append(val)
                            except ValueError:
                                continue
                if data:
                    self.current_csv_data = np.array(data)
            except Exception as e:
                self.status.config(text=f"加载 csv 失败: {e}")

        # 更新显示 - 自动适配对比度
        self._auto_contrast(self.current_movie)
        self.movie_viewer.set_movie(self.current_movie, self.vmin.get(), self.vmax.get())

        # 曲线
        if self.current_csv_data is not None:
            self.plotter.set_data(self.current_csv_data)
        else:
            # 如果没有 csv，使用 tif 计算平均值
            intensities = np.mean(self.current_movie, axis=(1, 2))
            self.plotter.set_data(intensities)
        self.plotter.set_frame(0)

        # UI
        self.spot_label.config(text=f"Spot: {self.current_spot_idx + 1}/{len(self.spot_files)} (ID: {spot_id})")
        self._update_slider()

        # 标注状态
        anno = self.annotations.get(spot_id, {})
        self.qualified_var.set(anno.get('qualified', ''))
        self.label_var.set(anno.get('labels', ''))  # 注意：改为 labels
        self.cutoff_start.set(anno.get('cutoff_start', ''))
        self.cutoff_end.set(anno.get('cutoff_end', ''))

        # 更新标注状态显示
        self._update_anno_status(anno)

        # 如果有 cutoff，调整曲线显示范围并跳转到中间帧
        cutoff_s = anno.get('cutoff_start', '')
        cutoff_e = anno.get('cutoff_end', '')
        if cutoff_s and cutoff_e:
            try:
                start = int(cutoff_s)
                end = int(cutoff_e)
                self.plotter.set_xlim(start, end)

                # 跳转到 cutoff 范围的中间帧
                mid_frame = (start + end) // 2
                if 0 <= mid_frame < self.movie_viewer.total_frames:
                    self.movie_viewer._show_frame(mid_frame)
                    self.frame_slider.set(mid_frame)
                    self.frame_label.config(text=f"{mid_frame + 1}/{self.movie_viewer.total_frames}")
                    self.plotter.set_frame(mid_frame)
            except ValueError:
                pass

        self._update_stats()

    def _on_frame_change(self, idx):
        """帧变化回调"""
        self.plotter.set_frame(idx)
        self.frame_label.config(text=f"{idx + 1}/{self.movie_viewer.total_frames}")

    def _update_slider(self):
        """更新滑块"""
        n = self.movie_viewer.total_frames
        self.frame_slider.config(from_=0, to=max(0, n - 1))
        self.frame_slider.set(0)
        self.frame_label.config(text=f"1/{n}")

    def _goto_frame(self, idx):
        self.movie_viewer.set_frame(idx)

    def _goto_last(self):
        self.movie_viewer.set_frame(self.movie_viewer.total_frames - 1)

    def _prev_frame(self):
        if self.movie_viewer.current_frame > 0:
            self.movie_viewer.set_frame(self.movie_viewer.current_frame - 1)

    def _next_frame(self):
        if self.movie_viewer.current_frame < self.movie_viewer.total_frames - 1:
            self.movie_viewer.set_frame(self.movie_viewer.current_frame + 1)

    def _on_anno(self):
        """标注变化"""
        if not self.spot_files:
            return

        spot_id = self.spot_files[self.current_spot_idx][0]
        labels_str = self.label_var.get().strip()
        self.annotations[spot_id] = {
            'qualified': self.qualified_var.get(),
            'labels': labels_str,
            'cutoff_start': self.cutoff_start.get(),
            'cutoff_end': self.cutoff_end.get()
        }

        # 如果是新标签，添加到候选列表（支持逗号分隔的多标签）
        if labels_str:
            for lbl in labels_str.split(','):
                lbl = lbl.strip()
                if lbl and lbl not in self.labels:
                    self.labels.append(lbl)
            self.labels.sort()
            self.label_combo['values'] = self.labels

        self._save_annotations()
        self._update_stats()

    def _clear_cutoff(self):
        """清除 cutoff"""
        self.cutoff_start.set('')
        self.cutoff_end.set('')
        self._on_anno()

    def _reset_view(self):
        """重置视图，关闭 cutoff 显示完整曲线"""
        self.plotter.reset_zoom()
        # 跳转到第一帧
        self.movie_viewer.set_frame(0)
        self.frame_slider.set(0)
        self.frame_label.config(text=f"1/{self.movie_viewer.total_frames}")

    def _add_label(self):
        """添加当前标签到列表"""
        label = self.label_var.get().strip()
        if label and label not in self.labels:
            self.labels.append(label)
            self.labels.sort()
            self.label_combo['values'] = self.labels

    def _update_anno_status(self, anno):
        """更新标注状态显示"""
        qualified = anno.get('qualified', '')

        if qualified == 'qualified':
            status_text = "✓ 已标注: 合格"
            status_color = "green"
        elif qualified == 'unqualified':
            status_text = "✗ 已标注: 不合格"
            status_color = "red"
        else:
            status_text = "○ 未标注"
            status_color = "gray"

        self.anno_status_label.config(text=status_text, foreground=status_color)

    def _quick_annotate(self, value):
        """快捷键标注"""
        self.qualified_var.set(value)
        self._on_anno()
        # 增量标注: 自动跳转到下一个未标记的
        if value in ('qualified', 'unqualified'):
            self._next_unmarked()

    def _next_unmarked(self):
        """跳转到下一个未标记的 spot"""
        if not self.spot_files:
            return

        self._on_anno()  # 自动保存当前标注

        # 从当前+1开始查找
        for i in range(self.current_spot_idx + 1, len(self.spot_files)):
            spot_id = self.spot_files[i][0]
            if self.annotations.get(spot_id, {}).get('qualified', '') == '':
                self.current_spot_idx = i
                self._load_spot()
                return

        # 从头查找
        for i in range(0, self.current_spot_idx):
            spot_id = self.spot_files[i][0]
            if self.annotations.get(spot_id, {}).get('qualified', '') == '':
                self.current_spot_idx = i
                self._load_spot()
                return

        self.status.config(text="所有 spots 已标注完成")

    def _update_stats(self):
        """更新统计"""
        q = sum(1 for a in self.annotations.values() if a.get('qualified') == 'qualified')
        u = sum(1 for a in self.annotations.values() if a.get('qualified') == 'unqualified')
        total = len(self.spot_files)
        self.stats_label.config(text=f"合格: {q} | 不合格: {u} | 未标记: {total - q - u}")

    def _jump_to_spot(self):
        """根据输入的 ID 跳转到对应 spot"""
        target_id = self.jump_id_var.get().strip()
        if target_id == "跳转到Spot ID":
            return
        if not target_id or not self.spot_files:
            return

        self._on_anno()  # 自动保存当前标注

        # 精确匹配
        for i, (spot_id, _, _) in enumerate(self.spot_files):
            if spot_id == target_id:
                self.current_spot_idx = i
                self._load_spot()
                return

        # 模糊匹配（包含关系）
        matches = [i for i, (sid, _, _) in enumerate(self.spot_files) if target_id in sid]
        if len(matches) == 1:
            self.current_spot_idx = matches[0]
            self._load_spot()
        elif len(matches) > 1:
            self.status.config(text=f"找到 {len(matches)} 个匹配项，请输入更精确的 ID")
        else:
            self.status.config(text=f"未找到匹配的 spot ID: {target_id}")

    def _prev_spot(self):
        if self.spot_files and self.current_spot_idx > 0:
            self._on_anno()  # 自动保存当前标注
            self.current_spot_idx -= 1
            self._load_spot()

    def _next_spot(self):
        if self.spot_files and self.current_spot_idx < len(self.spot_files) - 1:
            self._on_anno()  # 自动保存当前标注
            self.current_spot_idx += 1
            self._load_spot()

    def _apply_contrast(self):
        self.movie_viewer.set_contrast(self.vmin.get(), self.vmax.get())

    def _auto_contrast(self, movie_data):
        """根据 movie 数据自动适配对比度"""
        if movie_data is None or movie_data.size == 0:
            return

        # 使用百分位数来自动适配对比度
        # 忽略 0 值（通常是背景）来计算
        non_zero = movie_data[movie_data > 0]
        if len(non_zero) == 0:
            non_zero = movie_data.flatten()

        # 使用 1% 和 99% 百分位数
        vmin = float(np.percentile(non_zero, 1))
        vmax = float(np.percentile(non_zero, 99))

        self.vmin.set(round(vmin, 1))
        self.vmax.set(round(vmax, 1))

    def _export_csv(self):
        """导出合格的 spot 数据为 CSV"""
        if not self.spots_dir:
            messagebox.showwarning("提示", "请先加载 spots 目录")
            return

        # 统计合格的 spot
        qualified_spots = [(spot_id, anno) for spot_id, anno in self.annotations.items()
                          if anno.get('qualified') == 'qualified']

        if not qualified_spots:
            messagebox.showinfo("提示", "没有合格的 spot 数据可导出")
            return

        # 尝试加载坐标信息
        spots_json_path = self.spots_dir.parent / f"{self.spots_dir.name}.json"
        coords_data = {}

        if spots_json_path.exists():
            try:
                with open(spots_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 尝试解析数据格式
                if isinstance(data, dict):
                    if 'spots' in data:
                        spots_list = data['spots']
                    else:
                        spots_list = data
                    # 支持多种格式
                    for item in spots_list:
                        if isinstance(item, dict):
                            spot_id = str(item.get('id', item.get('spot_id', '')))
                            x = item.get('x', item.get('X', ''))
                            y = item.get('y', item.get('Y', ''))
                            if spot_id:
                                coords_data[spot_id] = {'x': x, 'y': y}
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            spot_id = str(item.get('id', item.get('spot_id', '')))
                            x = item.get('x', item.get('X', ''))
                            y = item.get('y', item.get('Y', ''))
                            if spot_id:
                                coords_data[spot_id] = {'x': x, 'y': y}
            except Exception as e:
                self.status.config(text=f"加载坐标文件失败: {e}")
        else:
            self.status.config(text=f"未找到坐标文件: {spots_json_path.name}")

        # 选择保存路径
        csv_path = filedialog.asksaveasfilename(
            title="保存 CSV 文件",
            initialdir=str(self.spots_dir),
            initialfile=f"{self.spots_dir.name}_qualified.csv",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
        )

        if not csv_path:
            return

        try:
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['spot_id', 'x', 'y', 'qualified', 'labels', 'cutoff_start', 'cutoff_end'])

                for spot_id, anno in qualified_spots:
                    coord = coords_data.get(spot_id, {'x': '', 'y': ''})
                    x = coord['x']
                    y = coord['y']

                    labels = anno.get('labels', '')
                    cutoff_start = anno.get('cutoff_start', '')
                    cutoff_end = anno.get('cutoff_end', '')

                    # 如果没有设置 cutoff，使用默认值
                    if not cutoff_start:
                        cutoff_start = 0
                    if not cutoff_end:
                        # 尝试获取总帧数
                        for sid, tif_path, _ in self.spot_files:
                            if sid == spot_id:
                                try:
                                    movie = tifffile.imread(str(tif_path))
                                    if movie.ndim == 2:
                                        cutoff_end = 0
                                    else:
                                        cutoff_end = movie.shape[0] - 1
                                except:
                                    cutoff_end = ''
                                break

                    writer.writerow([spot_id, x, y, 'qualified', labels, cutoff_start, cutoff_end])

            self.status.config(text=f"已导出 {len(qualified_spots)} 条记录到 {Path(csv_path).name}")
            messagebox.showinfo("导出成功", f"已导出 {len(qualified_spots)} 条合格记录")

        except Exception as e:
            messagebox.showerror("导出失败", f"导出时发生错误: {e}")


def main():
    root = tk.Tk()
    SpotProfileCheckApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
