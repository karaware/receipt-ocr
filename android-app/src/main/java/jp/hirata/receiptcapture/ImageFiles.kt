package jp.hirata.receiptcapture

import android.graphics.*
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.FileOutputStream
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.*

object ReceiptNames {
    private val timestamp = DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC)
    fun payerToken(payer: String): String = Base64.getUrlEncoder().withoutPadding()
        .encodeToString(payer.toByteArray(Charsets.UTF_8))
    fun fileName(payer: String, id: String, at: Instant = Instant.now()) =
        "receipt__${payerToken(payer)}__${timestamp.format(at)}__${id}.jpg"
}

object ImageFiles {
    const val MAX_LONG_EDGE = 3000
    private const val JPEG_QUALITY = 92

    fun normalize(source: File, target: File) {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.path, bounds)
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / sample > MAX_LONG_EDGE * 2) sample *= 2
        val bitmap = BitmapFactory.decodeFile(source.path, BitmapFactory.Options().apply { inSampleSize = sample })
            ?: error("画像を読み込めません")
        val orientation = ExifInterface(source).getAttributeInt(
            ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL
        )
        val degrees = when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
        val rotated = if (degrees == 0f) bitmap else Bitmap.createBitmap(
            bitmap, 0, 0, bitmap.width, bitmap.height, Matrix().apply { postRotate(degrees) }, true
        ).also { bitmap.recycle() }
        val edge = maxOf(rotated.width, rotated.height)
        val scaled = if (edge <= MAX_LONG_EDGE) rotated else {
            val ratio = MAX_LONG_EDGE.toFloat() / edge
            Bitmap.createScaledBitmap(rotated, (rotated.width * ratio).toInt(), (rotated.height * ratio).toInt(), true)
                .also { rotated.recycle() }
        }
        target.parentFile?.mkdirs()
        FileOutputStream(target).use {
            check(scaled.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, it))
            it.fd.sync()
        }
        scaled.recycle()
    }

    fun stitchOrdered(sources: List<File>, target: File) {
        require(sources.isNotEmpty())
        val dimensions = sources.map { file ->
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.path, options)
            require(options.outWidth > 0 && options.outHeight > 0) { "画像を読み込めません: ${file.name}" }
            options.outWidth to options.outHeight
        }
        val width = dimensions.maxOf { it.first }.coerceAtMost(MAX_LONG_EDGE)
        val height = dimensions.sumOf { (w, h) -> (h * width.toFloat() / w).toInt() }
        require(height <= 20_000) { "長いレシートが大きすぎます。撮影枚数を減らしてください" }
        val output = Bitmap.createBitmap(width, height, Bitmap.Config.RGB_565)
        val canvas = Canvas(output).apply { drawColor(Color.WHITE) }
        var y = 0f
        sources.forEach { file ->
            val bitmap = BitmapFactory.decodeFile(file.path) ?: error("画像を読み込めません: ${file.name}")
            val partHeight = (bitmap.height * width.toFloat() / bitmap.width).toInt()
            val part = if (bitmap.width == width) bitmap else {
                Bitmap.createScaledBitmap(bitmap, width, partHeight, true).also { bitmap.recycle() }
            }
            canvas.drawBitmap(part, 0f, y, null)
            y += part.height
            part.recycle()
        }
        val temporary = File(target.parentFile, ".${target.name}.tmp")
        FileOutputStream(temporary).use {
            check(output.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, it)); it.fd.sync()
        }
        output.recycle()
        check(temporary.renameTo(target)) { "連結画像を確定できません" }
    }
}
