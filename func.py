import numpy as np
from PIL import Image
import torch
import subprocess
import json
import re
import os
import gc
import shutil
import time
import glob
from itertools import islice
from concurrent.futures import ThreadPoolExecutor,as_completed
from comfy.model_management import unload_all_models, soft_empty_cache

def get_xfade_transitions():
    try:
        #执行命令：ffmpeg -hide_banner -h filter=xfade 查看可用的转场效果，执行ffmpeg命令获取xfade过滤器帮助信息
        result = subprocess.run(
            ['ffmpeg', '-hide_banner', '-h', 'filter=xfade'],
            capture_output=True,
            text=True,
            check=True
        )
        
        # 命令输出在stderr中
        output = result.stdout if result.stdout else result.stderr
        print(output)
        # 使用正则表达式匹配所有transition行
        pattern = r'^\s*(\w+)\s+-?\d+\b'
        data = output.split('\n')
        if len(data) == 0:
            transitions = [
                'fade', 'wipeleft', 'wiperight', 'wipeup', 'wipedown',
                'slideleft', 'slideright', 'slideup', 'slidedown',
                'circlecrop', 'rectcrop', 'distance', 'fadeblack', 'fadewhite',
                'radial', 'smoothleft', 'smoothright', 'smoothup', 'smoothdown',
                'circleopen', 'circleclose', 'vertopen', 'vertclose',
                'horzopen', 'horzclose', 'dissolve', 'pixelize',
                'diagtl', 'diagtr', 'diagbl', 'diagbr',
                'hlslice', 'hrslice', 'vuslice', 'vdslice',
                'hblur', 'fadegrays', 'wipetl', 'wipetr', 'wipebl', 'wipebr',
                'squeezeh', 'squeezev', 'zoomin', 'fadefast', 'fadeslow',
                'hlwind', 'hrwind', 'vuwind', 'vdwind',
                'coverleft', 'coverright', 'coverup', 'coverdown',
                'revealleft', 'revealright', 'revealup', 'revealdown'
            ]  # 如果没有找到任何transition，使用默认的
        else:
            transitions = []
            for line in data:
                match = re.search(pattern, line)
                if match and match.group(1) != 'none' and match.group(1) != 'custom':
                    transitions.append(match.group(1))
                
        return sorted(transitions)
    
    except subprocess.CalledProcessError as e:
        print(f"执行ffmpeg命令出错: {e}")
        print(f"错误输出: {e.stderr}")
        return []
    except FileNotFoundError:
        print("错误: 找不到ffmpeg程序，请确保ffmpeg已安装并添加到系统PATH")
        return []

def copy_image(image_path, destination_directory):
    try:
        # 获取图片文件名
        image_name = os.path.basename(image_path)
        # 构建目标路径
        destination_path = os.path.join(destination_directory, image_name)
        # 检查目标路径是否已有相同文件，避免重复复制
        if not os.path.exists(destination_path):
            shutil.copy(image_path, destination_path)
        return destination_path
    except Exception as e:
        print(f"Error copying image {image_path}: {e}")
        return None

def copy_images_to_directory(image_paths, destination_directory):
    # 如果目标目录不存在，创建它
    if not os.path.exists(destination_directory):
        os.makedirs(destination_directory)

    # 使用字典来保持原始索引与路径的对应关系
    index_to_path = {i: image_path for i, image_path in enumerate(image_paths)}
    copied_paths = [None] * len(image_paths)

    # 使用多线程并行复制图片
    with ThreadPoolExecutor() as executor:
        # 提交所有任务
        futures = {executor.submit(copy_image, image_path, destination_directory): i for i, image_path in index_to_path.items()}
        
        # 等待所有任务完成并按顺序存储结果
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            if result is not None:
                copied_paths[index] = result

    # 返回按原始顺序排列的新路径
    return [path for path in copied_paths if path is not None]

def get_image_paths_from_directory(directory, start_index, length):
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff'}
    
    # 创建排序后的文件生成器，直接在生成器中过滤
    def image_generator():
        for filename in sorted(os.listdir(directory)):
            if os.path.splitext(filename)[1].lower() in image_extensions:
                yield os.path.join(directory, filename)

    # 使用islice获取所需的图像路径
    selected_images = islice(image_generator(), start_index, start_index + length)
    
    return list(selected_images)


# def get_image_paths_from_directory(directory, start_index, length):
#     # 获取目录下所有文件，并按照文件名排序
#     files = sorted(os.listdir(directory))
    
#     # 过滤掉非图片文件（这里只检查常见图片格式）
#     image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff'}
#     image_files = [f for f in files if os.path.splitext(f)[1].lower() in image_extensions]
    
#     # 获取从start_index开始的length个图片路径
#     selected_images = image_files[start_index:start_index + length]
    
#     # 返回完整路径列表
#     image_paths = [os.path.join(directory, image_file) for image_file in selected_images]
    
#     return image_paths

def generate_template_string(filename):
    match = re.search(r'\d+', filename)
    return re.sub(r'\d+', lambda x: f'%0{len(x.group())}d', filename) if match else filename

def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))

def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

def getVideoInfo(video_path):
    command = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 
            'stream=avg_frame_rate,duration,width,height', '-of', 'json', video_path
        ]
    # 运行ffprobe命令
    result = subprocess.run(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    # 将输出转化为字符串
    output = result.stdout.decode('utf-8').strip()
    print(output)
    data = json.loads(output)
    # 查找视频流信息
    if 'streams' in data and len(data['streams']) > 0:
        stream = data['streams'][0]  # 获取第一个视频流
        fps = stream.get('avg_frame_rate')
        if fps is not None:
            # 帧率可能是一个分数形式的字符串，例如 "30/1" 或 "20.233000"
            if '/' in fps:
                num, denom = map(int, fps.split('/'))
                fps = num / denom
            else:
                fps = float(fps)  # 直接转换为浮点数
            width = int(stream.get('width'))
            height = int(stream.get('height'))
            duration = float(stream.get('duration'))
            return_data = {'fps': fps, 'width': width, 'height': height, 'duration': duration}
    else:
        return_data = {}
    return return_data

def get_image_size(image_path):
    # 打开图像文件
    with Image.open(image_path) as img:
        # 获取图像的宽度和高度
        width, height = img.size
        return width, height
    
def has_audio(video_path):
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-select_streams', 'a:0', 
        '-show_entries', 'stream=codec_type', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        video_path
    ]
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip() == 'audio'

def set_file_name(video_path):
    file_name = os.path.basename(video_path)
    file_extension = os.path.splitext(file_name)[1]
    #文件名根据年月日时分秒来命名
    file_name = time.strftime("%Y%m%d%H%M%S", time.localtime()) + file_extension
    return file_name

def video_type():
    return ('.mp4', '.avi', '.mov', '.mkv','.rmvb','.wmv','.flv')
def audio_type():
    return ('.mp3', '.wav', '.aac', '.flac','.m4a','.wma','.ogg','.amr','.ape','.ac3','.aiff','.opus','.m4b','.caf','.dts')

def validate_time_format(time_str):
    pattern = r'^([0-1][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9]|\d{1,2})$'
    return bool(re.match(pattern, time_str))

def get_video_files(directory):
    video_extensions = ['*.mp4', '*.avi', '*.mov', '*.mkv','*.rmvb', '*.wmv', '*.flv']
    video_files = []
    for ext in video_extensions:
        video_files.extend(glob.glob(os.path.join(directory, ext)))
    # 排序文件名
    video_files.sort()
    return video_files

def save_image(image, path):
    tensor2pil(image).save(path)
    
def clear_memory():
    gc.collect()
    unload_all_models()
    soft_empty_cache()