# -*- coding: utf-8 -*-
import os
import io
import struct
import shutil
from binascii import crc32
from sys import stdout
from concurrent.futures import ProcessPoolExecutor
from PIL import Image

class Unbuffered(object):
    def __init__(self, stream):
        self.stream = stream
    def write(self, data):
        self.stream.write(data)
        self.stream.flush()
    def __getattr__(self, attr):
        return getattr(self.stream, attr)

stdout = Unbuffered(stdout)


def str_codec(str_, method='decode'):
    codecs = ['ISO-8859-1', 'utf-8', 'cp1252']
    for codec in codecs:
        try:
            return getattr(str_, method)(codec)
        except Exception:
            pass
    return f"Texture_{crc32(str_)}"


def image_convert(img, mode, palette=None):
    if mode == 'P':
        if img.mode == 'RGBA':
            alpha = img.split()[-1]
            img_rgb = img.convert('RGB')
            img_p = img_rgb.convert('P', palette=Image.Palette.ADAPTIVE, colors=255)
            return img_p
        return img.convert(mode, palette=Image.Palette.ADAPTIVE, colors=256)
    return img.convert(mode)


# =========================================================================
# PARALLEL WORKER HELPERS FOR BATCH PROCESSING
# =========================================================================
def _pack_file_worker(args):
    file_path, f, bpp = args
    bpp2mode = {'8': 'P', '24': 'RGB', '32': 'RGBA', 'Alpha': 'L'}
    gettype = {'P': 1, 'L': 2, 'PaletteAlpha': 3, 'RGB': 4, 'RGBA': 5}
    raw_name = str_codec(os.path.splitext(f)[0], 'encode')
    
    with Image.open(file_path) as img:
        mode = bpp2mode.get(bpp, img.mode)
        img = image_convert(img, mode)
        im_data = img.tobytes()
        palette = bytes(map(lambda i: i >> 2, img.getpalette())) if mode == 'P' else b''
        
        full_bytes = im_data + palette
        CRC32 = crc32(full_bytes)
        
        two, checksum, size, name_len = 2, CRC32, len(full_bytes) + 12, len(raw_name)
        im_type, width, height = gettype.get(mode, 4), img.width, img.height
        
        return (two, checksum, size, name_len, raw_name, im_type, width, height, full_bytes)


def _swap_bgr_worker(img):
    if img.mode == 'RGB':
        r, g, b = img.split()
        return Image.merge('RGB', (b, g, r))
    elif img.mode == 'RGBA':
        r, g, b, a = img.split()
        return Image.merge('RGBA', (b, g, r, a))
    elif img.mode == 'P':
        palette_bytes = img.getpalette()
        if palette_bytes:
            new_palette = []
            for i in range(0, len(palette_bytes), 3):
                r = palette_bytes[i]
                g = palette_bytes[i+1]
                b = palette_bytes[i+2]
                new_palette.extend([b, g, r])
            
            img_swapped = img.copy()
            img_swapped.putpalette(new_palette)
            return img_swapped
    return img


def _save_unpacked_image_worker(args):
    mode, width, height, data, is_palette, out_file = args
    try:
        if is_palette:
            img = Image.frombytes(mode, (width, height), data[:-768])
            palette = map(lambda i: min(i << 2, 255), data[-768:])
            img.putpalette(palette)
        else:
            img = Image.frombytes(mode, (width, height), data)
        img.save(out_file)
    except Exception as e:
        print(f"Error saving {out_file}: {e}")


class tex_core(object):
    getmode = {1: 'P', 2: 'L', 3: 'P', 4: 'RGB', 5: 'RGBA'}
    bpp2mode = {'8': 'P', '24': 'RGB', '32': 'RGBA', 'Alpha': 'L'}
    gettype = {'P': 1, 'L': 2, 'PaletteAlpha': 3, 'RGB': 4, 'RGBA': 5}

    Palette = 1
    Alpha = 2
    PaletteAlpha = 3
    TrueColour = 4
    TrueColourAlpha = 5

    valid_format = ('.bmp', '.png', '.jpg', '.jpeg', '.webp')

    def get_texture_as_stream(self, mmp_path, texture_name):
        try:
            with open(mmp_path, 'rb') as f:
                header = f.read(4)
                if len(header) < 4: return None
                nTextures = struct.unpack('<I', header)[0]
                for _ in range(nTextures):
                    meta = f.read(14)
                    if len(meta) < 14: break
                    two, checksum, size, name_len = struct.unpack('<HIII', meta)
                    raw_name = f.read(name_len)
                    img_name = str_codec(raw_name)
                    
                    type_meta = f.read(12)
                    if len(type_meta) < 12: break
                    im_type, width, height = struct.unpack('<III', type_meta)
                    data_bytes = f.read(size - 12)
                    
                    clean_target = texture_name.rsplit('.', 1)[0].lower()
                    clean_current = img_name.rsplit('.', 1)[0].lower()
                    
                    if clean_current == clean_target:
                        mode = self.getmode.get(im_type, 'RGB')
                        if im_type == self.Palette or im_type == self.PaletteAlpha:
                            img = Image.frombytes(mode, (width, height), data_bytes[:-768])
                            palette = map(lambda i: min(i << 2, 255), data_bytes[-768:])
                            img.putpalette(palette)
                        else:
                            img = Image.frombytes(mode, (width, height), data_bytes)
                        
                        buf = io.BytesIO()
                        img.save(buf, format='PNG')
                        buf.seek(0)
                        return buf
        except Exception as e:
            print(f"Stream error: {e}")
        return None

    def unpack_all(self, source, output):
        os.makedirs(output, exist_ok=True)
        tasks = []
        with open(source, 'rb') as f:
            header = f.read(4)
            if len(header) < 4: return
            nTextures = struct.unpack('<I', header)[0]
            for _ in range(nTextures):
                meta = f.read(14)
                if len(meta) < 14: break
                two, checksum, size, name_len = struct.unpack('<HIII', meta)
                raw_name = f.read(name_len)
                img_name = str_codec(raw_name)
                im_type, width, height = struct.unpack('<III', f.read(12))
                data = f.read(size - 12)
                
                mode = self.getmode.get(im_type, 'RGB')
                is_palette = (im_type == self.Palette or im_type == self.PaletteAlpha)
                out_file = os.path.join(output, f"{img_name}.bmp")
                tasks.append((mode, width, height, data, is_palette, out_file))

        if len(tasks) > 4:
            max_workers = min(os.cpu_count() or 4, len(tasks))
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(_save_unpacked_image_worker, tasks))
        else:
            for t in tasks:
                _save_unpacked_image_worker(t)

    def unpack_subset(self, source, selection, output):
        os.makedirs(output, exist_ok=True)
        selection_lower = [s.lower().rsplit('.', 1)[0] for s in selection]
        tasks = []
        with open(source, 'rb') as f:
            header = f.read(4)
            if len(header) < 4: return
            nTextures = struct.unpack('<I', header)[0]
            for _ in range(nTextures):
                meta = f.read(14)
                if len(meta) < 14: break
                two, checksum, size, name_len = struct.unpack('<HIII', meta)
                raw_name = f.read(name_len)
                img_name = str_codec(raw_name)
                im_type, width, height = struct.unpack('<III', f.read(12))
                data = f.read(size - 12)
                
                if img_name.lower().rsplit('.', 1)[0] in selection_lower:
                    mode = self.getmode.get(im_type, 'RGB')
                    is_palette = (im_type == self.Palette or im_type == self.PaletteAlpha)
                    out_file = os.path.join(output, f"{img_name}.bmp")
                    tasks.append((mode, width, height, data, is_palette, out_file))

        if len(tasks) > 4:
            max_workers = min(os.cpu_count() or 4, len(tasks))
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(_save_unpacked_image_worker, tasks))
        else:
            for t in tasks:
                _save_unpacked_image_worker(t)

    def create_subset_mmp(self, source, selection, output):
        selection_lower = [s.lower().rsplit('.', 1)[0] for s in selection]
        items_to_keep = []
        with open(source, 'rb') as f:
            header = f.read(4)
            if len(header) < 4: return
            nTextures = struct.unpack('<I', header)[0]
            for _ in range(nTextures):
                meta = f.read(14)
                if len(meta) < 14: break
                two, checksum, size, name_len = struct.unpack('<HIII', meta)
                raw_name = f.read(name_len)
                img_name = str_codec(raw_name)
                data_segment = f.read(size)
                if img_name.lower().rsplit('.', 1)[0] in selection_lower:
                    items_to_keep.append((two, checksum, size, name_len, raw_name, data_segment))
        
        with open(output, 'wb') as f:
            f.write(struct.pack('<I', len(items_to_keep)))
            for two, checksum, size, name_len, raw_name, data_segment in items_to_keep:
                f.write(struct.pack('<HIII', two, checksum, size, name_len))
                f.write(raw_name)
                f.write(data_segment)

    def swapBGR(self, paths=[], cmd=False):
        valid_paths = [p for p in paths if os.path.isfile(p) and p.lower().endswith(self.valid_format)]
        if not valid_paths:
            return

        if len(valid_paths) > 4:
            max_workers = min(os.cpu_count() or 4, len(valid_paths))
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(_swap_bgr_worker, valid_paths))
        else:
            for p in valid_paths:
                _swap_bgr_worker(p)

    def StdUnify(self, path=None, format_=['mmp', 'bmp', 'png'], keeplevel=False, cmd=False):
        if not path or not os.path.exists(path): return
        for root, _, files in os.walk(path, topdown=False):
            for name in files:
                ext = os.path.splitext(name)[1].lower().lstrip('.')
                if not format_ or ext in format_:
                    old_path = os.path.join(root, name)
                    new_path = os.path.join(root, name.lower())
                    if old_path != new_path:
                        try: os.rename(old_path, new_path)
                        except Exception: pass

    def packing(self, paths=[], bpp=None, overwrite=False, output_mmp=None, cmd=False):
        for p in paths:
            if os.path.isdir(p):
                target_mmp = output_mmp if output_mmp else f"{p}.mmp"
                files = [f for f in os.listdir(p) if f.lower().endswith(self.valid_format)]
                if not files: continue

                tasks = [(os.path.join(p, f), f, bpp) for f in files]

                if len(files) > 4:
                    max_workers = min(os.cpu_count() or 4, len(files))
                    with ProcessPoolExecutor(max_workers=max_workers) as executor:
                        results = list(executor.map(_pack_file_worker, tasks))
                else:
                    results = [_pack_file_worker(t) for t in tasks]

                with open(target_mmp, 'wb') as mmp_f:
                    mmp_f.write(struct.pack('<I', len(results)))
                    for res in results:
                        two, checksum, size, name_len, raw_name, im_type, width, height, full_bytes = res
                        mmp_f.write(struct.pack('<HIII', two, checksum, size, name_len))
                        mmp_f.write(raw_name)
                        mmp_f.write(struct.pack('<III', im_type, width, height))
                        mmp_f.write(full_bytes)

    def tobpp(self, paths=[], bpp='8', output_mmp=None, cmd=False):
        for p in paths:
            if os.path.isfile(p) and p.lower().endswith('.mmp'):
                target = output_mmp if output_mmp else f"{os.path.splitext(p)[0]}_to{bpp}bpp.mmp"
                temp_extract = f"{p}_temp_bpp"
                self.unpack_all(p, temp_extract)
                self.packing(paths=[temp_extract], bpp=bpp, overwrite=True, output_mmp=target, cmd=False)
                shutil.rmtree(temp_extract, ignore_errors=True)

    def todat(self, mmp_path, output_dat_path, cmd=False):
        if os.path.isfile(mmp_path) and mmp_path.lower().endswith('.mmp'):
            with open(output_dat_path, 'w', encoding='utf-8') as dat_file:
                dat_file.write('1\n')
                with open(mmp_path, 'rb') as mmp_file:
                    header = mmp_file.read(4)
                    if len(header) < 4: return
                    nTextures = struct.unpack('<I', header)[0]
                    for _ in range(nTextures):
                        meta = mmp_file.read(14)
                        if len(meta) < 14: break
                        two, checksum, size, name_len = struct.unpack('<HIII', meta)
                        raw_name = mmp_file.read(name_len)
                        name = str_codec(raw_name)
                        mmp_file.seek(size, 1)
                        dat_file.write(f"{name}.bmp\n{name}\n")