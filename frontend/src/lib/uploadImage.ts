/** 上传图片的会话级暂存：压缩 + 缩略图 objectURL。
 *  图片只在内存里（隐私：刷新即失效），结果页/处理中页展示缩略图用。
 */

let lastImageUrl: string | null = null;

/** 压缩到长边 1280px / JPEG 0.85（视觉模型足够清晰，上传与读图都快）；
 *  无法解码的格式（HEIC 等）原样返回，由后端兜底处理。 */
export async function compressForUpload(file: File): Promise<File> {
  try {
    if (!/^image\/(jpeg|png)$/i.test(file.type)) return file;
    const bitmap = await createImageBitmap(file);
    const MAX_EDGE = 1280;
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
    // 小图且体积不大就不动
    if (scale >= 1 && file.size <= 400 * 1024) return file;
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement('canvas');
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext('2d');
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', 0.85),
    );
    if (!blob) return file;
    return new File([blob], file.name.replace(/\.(png|jpe?g|heic|heif)$/i, '.jpg'), {
      type: 'image/jpeg',
    });
  } catch {
    return file;
  }
}

export function setLastImage(blob: Blob): void {
  if (lastImageUrl) URL.revokeObjectURL(lastImageUrl);
  lastImageUrl = URL.createObjectURL(blob);
}

export function getLastImage(): string | null {
  return lastImageUrl;
}

export function clearLastImage(): void {
  if (lastImageUrl) URL.revokeObjectURL(lastImageUrl);
  lastImageUrl = null;
}
