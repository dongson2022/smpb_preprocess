# 单分子成像数据预处理工具

本工具集适用于 Nikon N-STORM 单分子荧光显微镜采集的xyt/xyct成像数据的预处理，包括spot intensity trace的提取和检查。

## 工具列表

| 工具 | 功能 | 输入 | 输出 |
|------|------|------|------|
| spot_extractor.py | Spot 数据提取 | ND2 文件 | TIFF + JSON + CSV |
| spot_profile_check.py | Spot 数据检查 | Spots 目录 | CSV |

## 依赖安装

```bash
pip install aicsimageio[nd2] tifffile matplotlib numpy scikit-image pillow natsort
```

---

## spot_extractor.py - 光斑提取工具

从 ND2 原始数据一站式完成最大投影、光斑检测、原始视频和荧光强度时间曲线提取。

### 使用方法

<img width="2252" height="1698" alt="image" src="https://github.com/user-attachments/assets/95aa230a-f022-4b72-902f-85541a8f35b4" />


```bash
python spot_extractor.py
```

### 功能特点

- **单文件处理**: 选择单个 ND2 文件作为输入
- **多通道支持**: 下拉菜单切换不同通道
- **最大投影**: 自动生成并保存各通道的最大投影
- **光斑检测**: 基于 `blob_log` 算法检测高斯光斑
- **原始视频提取**: 从 ND2 中截取每个 spot 的时间序列视频
- **强度曲线计算**: 计算每个 spot 的荧光强度随时间变化

### 操作流程

1. **选择 ND2 文件** - 加载原始成像数据
2. **选择通道** - 从下拉菜单选择要处理的通道
3. **生成最大投影** - 点击"生成最大投影"按钮
4. **调整参数** - 设置预处理、检测参数和 Camera Offset
5. **检测光斑** - 点击"检测当前通道"
6. **提取数据** - 点击"提取所有 Spot 视频"或"一键处理"

### 输出文件

假设输入文件为 `sample.nd2`，处理后生成：

```
sample.nd2
├── sample_ch1_max.tif          # 通道 1 最大投影
├── sample_ch1_spots.json       # 通道 1 检测结果
└── sample_ch1_spots/           # 通道 1 Spot 数据目录
    ├── 1.tif                   # Spot #1 原始视频 (时间序列)
    ├── 1.csv                   # Spot #1 强度曲线
    ├── 2.tif
    ├── 2.csv
    └── ...
```

### 强度计算方法

每个 spot 的强度时间曲线计算方式：
- 截取以 spot 中心为原点的 `box_size × box_size` 区域
- 每帧强度 = (所有像素值 - Camera Offset) 的平均值
- Camera Offset 默认值为 100，可根据实际背景值调整

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| Median 半径 | 2 | 中值滤波去噪半径 |
| Min Sigma | 3.0 | 最小光斑大小 |
| Max Sigma | 5.0 | 最大光斑大小 |
| Num Sigma | 3 | sigma 采样数 |
| Threshold | 0.03 | 检测阈值 |
| Box Size | 7 | 截取方框边长 (像素)，建议内接于虚线圆 |
| Camera Offset | 100 | 相机背景信号 |

### 输出格式

**JSON 检测结果** (`sample_ch1_spots.json`):

```json
{
  "source_file": "sample.nd2",
  "channel": 1,
  "image_shape": [512, 512],
  "parameters": {
    "preprocessing": {"median_size": 2},
    "detection": {"min_sigma": 3.0, "max_sigma": 5.0, "num_sigma": 3, "threshold": 0.03},
    "display": {"box_size": 7}
  },
  "spots": [
    {"id": 0, "x": 100.5, "y": 200.3, "radii": 4.2, "intensity": 5000},
    ...
  ],
  "spot_count": 50
}
```

**CSV 强度曲线** (`1.csv`):

```csv
frame,intensity
0,123.5
1,125.2
2,124.8
...
```

### 快捷操作

| 操作 | 方式 |
|------|------|
| 缩放 | 鼠标滚轮 |
| 平移 | 右键拖拽 |
| 一键处理 | 自动完成投影→检测→提取全流程 |

---

## spot_profile_check.py - Spot Intensity Trace检查工具

<img width="2102" height="1278" alt="image-1" src="https://github.com/user-attachments/assets/ddb4ef06-9103-4317-9689-786627df033b" />


检查和标注提取的 spot intensity trace 数据，支持导出合格数据为 CSV。

### 使用方法

```bash
python spot_profile_check.py
```

### 功能特点

- **视频预览**: 显示 spot 的 tif 时间序列视频
- **强度曲线**: 显示 spot 的荧光强度随时间变化（来自 CSV）
- **数据标注**: 标记 spot 为合格/不合格
- **多标签支持**: 支持添加多个标签（逗号分隔）
- **Cutoff 范围**: 设置有效数据范围，曲线自动缩放
- **CSV 导出**: 导出合格的 spot 数据，包含坐标信息

### 操作流程

1. **打开目录** - 选择 `{name}_spots/` 目录
2. **浏览数据** - 查看视频和强度曲线，使用帧导航或滑块跳转
3. **标注** - 设置合格/不合格状态、标签、cutoff 范围
4. **导出** - 点击"导出 CSV"保存合格数据

### 标注功能

| 功能 | 操作 |
|------|------|
| 标记合格 | 点击"合格"或按 `Q` |
| 标记不合格 | 点击"不合格"或按 `W` |
| 清除标注 | 按 `E` |
| 下一个未标记 | 按 `Space` |
| 切换 Spot | 按 `←` / `→` |

### Cutoff 范围

设置有效数据范围后：
- 曲线自动缩放到指定范围
- 视频自动跳转到范围中间帧
- 导出时记录 cutoff 值

### 输出文件

**标注文件** (`{spots_dir}/annotations.json`):

```json
{
  "directory": "path/to/spots",
  "total_spots": 100,
  "qualified_count": 50,
  "unqualified_count": 20,
  "annotations": {
    "1": {
      "qualified": "qualified",
      "labels": "good,bright",
      "cutoff_start": "10",
      "cutoff_end": "90"
    }
  }
}
```

**CSV 导出** (`{spots_dir}_qualified.csv`):

```csv
spot_id,x,y,qualified,labels,cutoff_start,cutoff_end
1,100.5,200.3,qualified,good,bright,10,90
2,150.2,180.7,qualified,,0,99
```

> **注意**: 坐标信息从父目录的 `{spots_dir}.json` 文件读取（由 spot_finder 或 spot_extractor 生成）

### 引用

如果您在研究工作中使用了本工具，请引用以下文献：

> Yao Xie et al., "Single-Molecule DNA Hybridization on Tetrahedral DNA Framework-Modified Surfaces", *Nano Letters*, 2025, DOI: [10.1021/acs.nanolett.5c01507](https://doi.org/10.1021/acs.nanolett.5c01507)

您的引用对我们持续开发和维护这些工具非常重要，感谢支持！
