import json
import functools
import numpy as np
from decimal import *
from typing import Type
from loguru import logger

TARGET_SAMPLERATE = 16000
@functools.total_ordering
class AudioPacket(object):
    """Represents a "Packet" of audio data."""
    resampling = 0
    resampler = None

    def __init__(self, data_json, resample=True, is_processed=False):
        """ Initialize AudioPacket from json data or bytes

        Args:
            data_json (dict or bytes): json data or bytes
        """
        if not isinstance(data_json, dict):
            data_json = json.loads(str(data_json))

        self.sample_rate = int(data_json['sampleRate'])
        self.num_channels = int(data_json['numChannels'])
        self.timestamp = data_json['timestamp'] # ms

        if not is_processed:
            self.bytes = self.preprocess_audio_buffer(
                data_json.get('bytes', data_json.get('audio')),
                resample=resample
            )
        else:
            self.bytes = data_json['bytes']

        self.frame_size = len(self.bytes)

        self.duration = data_json.get('duration') # ms
        if self.duration is None:
            self.duration = (self.frame_size/self.sample_rate)/(self.num_channels*4)
            self.duration *= 1000 # ms
        self.id = data_json.get('packetID')

    @staticmethod
    def verify_format(data_json):
        """Verify that data_json is in the correct format

        Args:
            data_json (dict): json data
        """
        for key in ['sampleRate', 'bytes', 'numChannels']:
            if key not in data_json.keys():
                raise Exception(f"Invalid AudioPacket format: {key} not in {data_json.keys()}")

    def get_float(self):
        """ Get audio buffer as float

        Returns:
            np.array(float): audio buffer as float
        """
        return np.frombuffer(self.bytes, dtype=np.float32).copy()

    def preprocess_audio_buffer(self, buffer, resample=True):
        """ Preprocess audio buffer to 16k 1ch int16 bytes format

        Args:
            buffer Union(np.array(float)): audio buffer
            sample_rate (int): sample rate of buffer
            num_channels (int): number of channels of buffer

        Returns:
            bytes: preprocessed audio buffer
        """

        # Convert to a NumPy array of float32
        if isinstance(buffer, bytes):
            if buffer == b'':
                # DUMMY AUX PACKET
                return buffer
            buffer_float = np.frombuffer(buffer, dtype=np.float32)
        else:
            buffer_float = np.array(buffer).astype(np.float32)

        # buffer_float = buffer_float.copy()*2.0 # Gain

        # Merge Channels if > 1
        if self.num_channels > 1:
            # TODO revise
            # logger.warning(f"AudioPacket has {self.num_channels} channels, merging to 1 channel")
            src_num_channels = self.num_channels
            one_channel_buffer = np.zeros(len(buffer_float)//src_num_channels, dtype=np.float32)
            channel_contribution = 1/src_num_channels
            for i in range(len(one_channel_buffer)):
                for channel_i in range(src_num_channels):
                    one_channel_buffer[i] +=\
                        buffer_float[i*src_num_channels + channel_i]*channel_contribution
            self.num_channels = 1
        else:
            one_channel_buffer = buffer_float


        # Downsample if necesssary: buffer_16k_1ch
        src_sample_rate = self.sample_rate
        if TARGET_SAMPLERATE != src_sample_rate and resample:
            self.bytes = one_channel_buffer.tobytes()
            self.resample(TARGET_SAMPLERATE, copy=False)
            return self.bytes
        else:
            return one_channel_buffer.tobytes()

    def resample(self, target_sample_rate, copy=True):
        # try:
        if target_sample_rate == self.sample_rate:
            return self

        # increment resampling counter
        AudioPacket.resampling += 1

        import torch
        from torchaudio import functional as F
        from torchaudio.transforms import Resample
        one_channel_buffer = np.frombuffer(self.bytes, dtype=np.float32)
        waveform = torch.from_numpy(one_channel_buffer.copy())

        # check if resampler is defined and matching the same sample rates
        if AudioPacket.resampler is None or\
            AudioPacket.resampler.orig_freq != self.sample_rate or\
                AudioPacket.resampler.new_freq != target_sample_rate:
            AudioPacket.resampler = Resample(self.sample_rate, target_sample_rate)
            print(f"Resampling {self.sample_rate} -> {target_sample_rate}")

        audio_resampled = AudioPacket.resampler(waveform)
        audio_resampled = audio_resampled.numpy().tobytes()

        if copy:
            from copy import deepcopy
            audio_packet = deepcopy(self)
            audio_packet.bytes = audio_resampled
            audio_packet.sample_rate = target_sample_rate
            return audio_packet
        else:
            self.bytes = audio_resampled
            self.sample_rate = target_sample_rate
            return self

    def __add__(self, _audio_packet: Type['AudioPacket']):
        """ Add two audio packets together and return new packet with combined bytes

        Args:
            _audio_packet (AudioPacket): AudioPacket to add

        Returns:
            AudioPacket: New AudioPacket with combined bytes
        """
        # ensure no errs, and snippets are consecutive
        # TODO verify + duration work
        # if self >= _audio_packet:
        #     raise Exception(
        #         f"Audio Packets are not in order: {self.timestamp} > {_audio_packet.timestamp}"
        #     )

        # assert self.sample_rate == _audio_packet.sample_rate, f"Sample rates do not match: {self.sample_rate} != {_audio_packet.sample_rate}"
        # assert self.num_channels == _audio_packet.num_channels, f"Num channels do not match: {self.num_channels} != {_audio_packet.num_channels}"
        # assert self.duration == _audio_packet.duration, f"Durations do not match: {self.duration} != {_audio_packet.duration}"
        # assert self.timestamp + self.duration <= _audio_packet.timestamp, f"Audio Packets are not consecutive: {self.timestamp} + {self.duration} = {self.timestamp + self.duration} > {_audio_packet.timestamp}"
        # if self.timestamp + self.duration > _audio_packet.timestamp:
        #     import math
        #     if math.isclose(self.timestamp + self.duration, _audio_packet.timestamp, abs_tol=0.0001):
        #         _audio_packet.timestamp = self.timestamp + self.duration
        #     else:
        #         raise Exception(
        #             f"Audio Packets are not consecutive: {self.timestamp} + {self.duration} > {_audio_packet.timestamp}, {self.timestamp + self.duration - _audio_packet.timestamp}"
        #         )

        timestamp = self.timestamp
        if self.bytes == b'': # DUMMY AUX PACKET
            timestamp = _audio_packet.timestamp

        return AudioPacket(
            {
                "bytes": self.bytes + _audio_packet.bytes,
                "timestamp": timestamp,
                "sampleRate": _audio_packet.sample_rate, # NOTE: assumes same sample rate,
                "numChannels": _audio_packet.num_channels # NOTE: assumes same num channels
            },
            resample=False,
            is_processed=True
        )

    def __getitem__(self, key):
        """ Get item from AudioPacket

        Args:
            key (int or slice): index or slice

        Returns:
            AudioPacket: new AudioPacket with sliced bytes
        """
        if isinstance(key, slice):
            # Note that step != 1 is not supported
            start, stop, step = key.indices(len(self))
            if step != 1:
                raise (NotImplementedError, "step != 1 not supported")

            if start < 0:
                raise (NotImplementedError, "start < 0 not supported")

            if stop > len(self):
                raise (NotImplementedError, "stop > len(self) not supported")

            # calculate new timestamp
            calculated_timestamp = self.timestamp + float((start/self.frame_size))*self.duration

            return AudioPacket(
                {
                    "bytes": self.bytes[start:stop],
                    "timestamp": calculated_timestamp,
                    "sampleRate": self.sample_rate,
                    "numChannels": self.num_channels
                },
                resample=False,
                is_processed=True
            )

        elif isinstance(key, int):
            raise (NotImplementedError, "value as index; only slices")
        elif isinstance(key, tuple):
            raise (NotImplementedError, "Tuple as index; only slices")
        else:
            raise (TypeError, 'Invalid argument type: {}'.format(type(key)))

    def __str__(self) -> str:
        return f'{self.timestamp}, {self.duration}, {len(self.bytes)}'

    def __eq__(self, __o: object) -> bool:
        return self.timestamp == __o.timestamp
    # and self.bytes == __o.bytes

    def __lt__(self, __o: object) -> bool:
        # TODO verify + duration work
        # return self.timestamp + self.duration <= __o.timestamp
        return self.timestamp < __o.timestamp

    def __len__(self) -> int:
       return len(self.bytes)

    @staticmethod
    def get_null_packet():
        """ Get null/dummy AudioPacket"""
        return AudioPacket(
            {
                "bytes": b"",
                "timestamp": 0,
                "sampleRate": 0,
                "numChannels": 0      ,
                "duration": 0.0,
            },
            resample=False,
            is_processed=True
        )