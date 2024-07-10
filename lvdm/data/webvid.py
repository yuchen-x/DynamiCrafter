
import torch
import os
import random
import pandas as pd
import cv2
import numpy as np

from tqdm import tqdm
from decord import VideoReader, cpu
from torch.utils.data import Dataset
from torch.utils.data import DataLoader
from torchvision import transforms


class WebVid(Dataset):
    """
    WebVid Dataset.
    Assumes webvid data is structured as follows.
    Webvid/
        videos/
            000001_000050/      ($page_dir)
                1.mp4           (videoid.mp4)
                ...
                5000.mp4
            ...
    """
    def __init__(
        self,
        meta_path,
        data_dir,
        subsample=None,
        video_length=16,
        resolution=[256, 512],
        frame_stride=1,
        frame_stride_min=1,
        spatial_transform=None,
        crop_resolution=None,
        fps_max=None,
        load_raw_resolution=False,
        fixed_fps=None,
        random_fs=False,
    ):
        self.meta_path = meta_path
        self.data_dir = data_dir
        self.subsample = subsample
        self.video_length = video_length
        self.resolution = [resolution, resolution] if isinstance(
            resolution, int) else resolution
        self.fps_max = fps_max
        self.frame_stride = frame_stride
        self.frame_stride_min = frame_stride_min
        self.fixed_fps = fixed_fps
        self.load_raw_resolution = load_raw_resolution
        self.random_fs = random_fs
        self._load_metadata()
        if spatial_transform is not None:
            if spatial_transform == "random_crop":
                self.spatial_transform = transforms.RandomCrop(crop_resolution)
            elif spatial_transform == "center_crop":
                self.spatial_transform = transforms.Compose([
                    transforms.CenterCrop(resolution),
                ])
            elif spatial_transform == "resize_center_crop":
                # assert(self.resolution[0] == self.resolution[1])
                self.spatial_transform = transforms.Compose([
                    transforms.Resize(min(self.resolution)),
                    transforms.CenterCrop(self.resolution),
                ])
            elif spatial_transform == "resize":
                self.spatial_transform = transforms.Resize(self.resolution)
            else:
                raise NotImplementedError
        else:
            self.spatial_transform = None

        # add fps and frame_stride statistics
        self.fps_stat = {}
        self.fs_stat = {}

    def _load_metadata(self):
        metadata = pd.read_csv(self.meta_path, dtype=str)
        print(f'>>> {len(metadata)} data samples loaded.')
        if self.subsample is not None:
            metadata = metadata.sample(self.subsample, random_state=0)

        metadata['caption'] = metadata['name']
        del metadata['name']
        self.metadata = metadata
        self.metadata.dropna(inplace=True)

    def _get_video_path(self, sample):
        rel_video_fp = os.path.join(sample['page_dir'],
                                    str(sample['videoid']) + '.mp4')
        full_video_fp = os.path.join(self.data_dir, 'videos', rel_video_fp)
        return full_video_fp

    def __getitem__(self, index):
        if self.random_fs:
            frame_stride = random.randint(self.frame_stride_min,
                                          self.frame_stride)
        else:
            frame_stride = self.frame_stride


        ## get frames until success
        while True:
            index = index % len(self.metadata)
            sample = self.metadata.iloc[index]
            video_path = self._get_video_path(sample)
            ## video_path should be in the format of "....../WebVid/videos/$page_dir/$videoid.mp4"
            caption = sample['caption']

            try:
                if self.load_raw_resolution:
                    video_reader = VideoReader(video_path, ctx=cpu(0))
                else:
                    video_reader = VideoReader(video_path,
                                               ctx=cpu(0),
                                               width=530,
                                               height=300)
                if len(video_reader) < self.video_length:
                    print(
                        f"video length ({len(video_reader)}) is smaller than target length({self.video_length})"
                    )
                    index += 1
                    continue
                else:
                    pass
            except:
                index += 1
                print(f"Load video failed! path = {video_path}")
                continue

            fps_ori = video_reader.get_avg_fps()
            if self.fixed_fps is not None:
                frame_stride = int(frame_stride *
                                   (1.0 * fps_ori / self.fixed_fps))

            ## to avoid extreme cases when fixed_fps is used
            frame_stride = max(frame_stride, 1)

            ## get valid range (adapting case by case)
            required_frame_num = frame_stride * (self.video_length - 1) + 1
            frame_num = len(video_reader)
            if frame_num < required_frame_num:
                ## drop extra samples if fixed fps is required
                if self.fixed_fps is not None and frame_num < required_frame_num * 0.5:
                    index += 1
                    continue
                else:
                    frame_stride = frame_num // self.video_length
                    required_frame_num = frame_stride * (self.video_length -
                                                         1) + 1

            ## select a random clip
            random_range = frame_num - required_frame_num
            start_idx = random.randint(0,
                                       random_range) if random_range > 0 else 0

            ## calculate frame indices
            frame_indices = [
                start_idx + frame_stride * i for i in range(self.video_length)
            ]
            try:
                frames = video_reader.get_batch(frame_indices)
                break
            except:
                print(
                    f"Get frames failed! path = {video_path}; [max_ind vs frame_total:{max(frame_indices)} / {frame_num}]"
                )
                index += 1
                continue


        # print('frame number: ', frame_num)
        # print('required_frame_num', required_frame_num)
        # print(fps_ori)
        # print(frame_stride)
        # print('random range', random_range)
        # print(frame_indices)
        # print('caption', caption)
        # output_file = f'./test_{index}.mp4'
        # fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        # out = cv2.VideoWriter(output_file, fourcc, 5, (256,320))
        # for img in frames.asnumpy():
        #     img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        #     out.write(img_bgr)
        # out.release()

        ## process data
        assert (frames.shape[0] == self.video_length
                ), f'{len(frames)}, self.video_length={self.video_length}'
        frames = torch.tensor(frames.asnumpy()).permute(
            3, 0, 1, 2).float()  # [t,h,w,c] -> [c,t,h,w]


        if self.spatial_transform is not None:
            frames = self.spatial_transform(frames)
            # frames = frames.permute(1,2,3,0)
            # frames = frames.type(torch.uint8)
            # output_file = f'./test_{index}.mp4'
            # fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            # out = cv2.VideoWriter(output_file, fourcc, 5, (512,320))
            # for img in frames.numpy():
            #     img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            #     out.write(img_bgr)
            # out.release()

        if self.resolution is not None:
            assert (frames.shape[2], frames.shape[3]) == (
                self.resolution[0], self.resolution[1]
            ), f'frames={frames.shape}, self.resolution={self.resolution}'

        ## turn frames tensors to [-1,1]
        frames = (frames / 255 - 0.5) * 2
        fps_clip = fps_ori // frame_stride
        if self.fps_max is not None and fps_clip > self.fps_max:
            fps_clip = self.fps_max

        data = {
            'video': frames,
            'caption': caption,
            'path': video_path,
            'fps': fps_clip,
            'frame_stride': frame_stride
        }

        self.fps_stat[fps_clip] = self.fps_stat.get(fps_clip, 0) + 1
        self.fs_stat[frame_stride] = self.fs_stat.get(frame_stride, 0) + 1 
        return data

    def __len__(self):
        return len(self.metadata)


if __name__ == "__main__":
    meta_path = "/home/yuchen-x/diska/datasets/open-x-videos/train/data.csv"  ## path to the meta file
    data_dir = "/home/yuchen-x/diska/datasets/open-x-videos/train"  ## path to the data directory
    save_dir = "./"  ## path to the save directory
    dataset = WebVid(meta_path,
                     data_dir,
                     subsample=None,
                     video_length=16,
                     resolution=[320, 512],
                     frame_stride=6,
                     spatial_transform="resize_center_crop",
                     crop_resolution=None,
                     fps_max=None,
                     load_raw_resolution=True,
                     random_fs=True)

    from tqdm import tqdm
    for idx in tqdm(range(1)):
        sample = dataset[0]

# dataloader = DataLoader(dataset,
#                         batch_size=1,
#                         num_workers=0,
#                         shuffle=False)

    # import sys
    # sys.path.insert(1, os.path.join(sys.path[0], '..', '..'))
    # from utils.save_video import tensor_to_mp4
    # for i, batch in tqdm(enumerate(dataloader), desc="Data Batch"):
    #     video = batch['video']
    #     name = batch['path'][0].split('videos/')[-1].replace('/', '_')
    #     tensor_to_mp4(video, save_dir + '/' + name, fps=8)
