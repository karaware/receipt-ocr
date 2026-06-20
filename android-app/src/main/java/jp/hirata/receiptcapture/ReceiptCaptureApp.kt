package jp.hirata.receiptcapture

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import jp.hirata.receiptcapture.data.*
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

private enum class Page { CAMERA, PENDING, SETTINGS }

@Composable
fun ReceiptCaptureApp(
    configured: Boolean,
    initialPayer: String,
    folderName: String,
    onConfigure: (String) -> Unit,
    onUpdatePayer: (String) -> Unit,
) {
    MaterialTheme(colorScheme = lightColorScheme(primary = androidx.compose.ui.graphics.Color(0xFF315C49))) {
        if (!configured) {
            Onboarding(initialPayer, onConfigure)
            return@MaterialTheme
        }
        val vm: ReceiptViewModel = viewModel()
        val state by vm.state.collectAsStateWithLifecycle()
        var page by remember { mutableStateOf(Page.CAMERA) }
        Scaffold(
            bottomBar = {
                NavigationBar {
                    NavigationBarItem(page == Page.CAMERA, { page = Page.CAMERA }, { Icon(Icons.Default.CameraAlt, null) }, label = { Text("撮影") })
                    NavigationBarItem(page == Page.PENDING, { page = Page.PENDING }, { BadgedBox({ if (state.pending.isNotEmpty()) Badge { Text(state.pending.size.toString()) } }) { Icon(Icons.Default.CloudUpload, null) } }, label = { Text("未送信") })
                    NavigationBarItem(page == Page.SETTINGS, { page = Page.SETTINGS }, { Icon(Icons.Default.Settings, null) }, label = { Text("設定") })
                }
            }
        ) { padding ->
            Box(Modifier.padding(padding)) {
                when (page) {
                    Page.CAMERA -> CameraPage(state, vm)
                    Page.PENDING -> PendingPage(state.pending, vm)
                    Page.SETTINGS -> SettingsPage(initialPayer, folderName, onUpdatePayer, onConfigure)
                }
            }
        }
        state.message?.let { message ->
            AlertDialog(onDismissRequest = vm::clearMessage, confirmButton = { TextButton(onClick = vm::clearMessage) { Text("OK") } }, text = { Text(message) })
        }
    }
}

@Composable
private fun Onboarding(initialPayer: String, onConfigure: (String) -> Unit) {
    var payer by remember { mutableStateOf(initialPayer) }
    Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
        Text("初期設定", style = MaterialTheme.typography.headlineMedium)
        Spacer(Modifier.height(12.dp))
        Text("支払者名を入力し、Google Driveの共有 receipt-inbox を選択してください。")
        Spacer(Modifier.height(20.dp))
        OutlinedTextField(payer, { payer = it }, Modifier.fillMaxWidth(), label = { Text("支払者名") }, singleLine = true)
        Spacer(Modifier.height(16.dp))
        Button({ onConfigure(payer) }, enabled = payer.trim().isNotEmpty(), modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Default.Folder, null); Spacer(Modifier.width(8.dp)); Text("Google Driveフォルダを選択")
        }
    }
}

@Composable
private fun CameraPage(state: ReceiptUiState, vm: ReceiptViewModel) {
    val captures = state.draft?.captures.orEmpty()
    val taking = state.takingPhoto || captures.isEmpty()
    Column(Modifier.fillMaxSize()) {
        if (captures.isEmpty()) {
            SingleChoiceSegmentedButtonRow(Modifier.padding(8.dp).fillMaxWidth()) {
                val mode = state.draft?.session?.mode ?: CaptureMode.MULTIPLE_RECEIPTS
                SegmentedButton(mode == CaptureMode.MULTIPLE_RECEIPTS, { vm.setMode(CaptureMode.MULTIPLE_RECEIPTS) }, shape = SegmentedButtonDefaults.itemShape(0, 2)) { Text("複数レシート") }
                SegmentedButton(mode == CaptureMode.LONG_RECEIPT, { vm.setMode(CaptureMode.LONG_RECEIPT) }, shape = SegmentedButtonDefaults.itemShape(1, 2)) { Text("長い1レシート") }
            }
        }
        Box(Modifier.weight(1f).fillMaxWidth().background(androidx.compose.ui.graphics.Color.Black)) {
            if (taking) CameraPreview(onPhoto = vm::photoSaved)
            else ReceiptPreview(captures.last().path)
            if (state.busy) CircularProgressIndicator(Modifier.align(Alignment.Center))
            Text("${captures.size}枚", color = androidx.compose.ui.graphics.Color.White, modifier = Modifier.align(Alignment.TopEnd).padding(12.dp).background(androidx.compose.ui.graphics.Color(0x99000000)).padding(8.dp))
        }
        if (!taking && captures.isNotEmpty()) {
            Column(Modifier.padding(8.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(vm::nextPhoto, Modifier.weight(1f)) { Text("次の撮影") }
                    Button(vm::queueUpload, Modifier.weight(1f)) { Text("アップロード") }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(vm::discardLast, Modifier.weight(1f)) { Text("直前を破棄") }
                    var confirm by remember { mutableStateOf(false) }
                    OutlinedButton({ confirm = true }, Modifier.weight(1f)) { Text("すべて破棄") }
                    if (confirm) AlertDialog(
                        onDismissRequest = { confirm = false },
                        confirmButton = { TextButton({ confirm = false; vm.discardAll() }) { Text("すべて破棄") } },
                        dismissButton = { TextButton({ confirm = false }) { Text("戻る") } },
                        text = { Text("今回撮影した${captures.size}枚を削除しますか？") },
                    )
                }
            }
        }
    }
}

@Composable
private fun ReceiptPreview(path: String) {
    val bitmap = remember(path) { BitmapFactory.decodeFile(path)?.asImageBitmap() }
    bitmap?.let { Image(it, null, Modifier.fillMaxSize(), contentScale = ContentScale.Fit) }
}

@Composable
private fun CameraPreview(onPhoto: (File) -> Unit) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) { if (!granted) permission.launch(Manifest.permission.CAMERA) }
    if (!granted) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Button({ permission.launch(Manifest.permission.CAMERA) }) { Text("カメラを許可") } }
        return
    }
    val lifecycleOwner = androidx.lifecycle.compose.LocalLifecycleOwner.current
    val executor = remember { Executors.newSingleThreadExecutor() }
    val imageCapture = remember { ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY).build() }
    DisposableEffect(Unit) { onDispose { executor.shutdown() } }
    Box(Modifier.fillMaxSize()) {
        AndroidView(
            factory = { ctx -> PreviewView(ctx).also { view ->
                val future = ProcessCameraProvider.getInstance(ctx)
                future.addListener({
                    val provider = future.get()
                    val preview = Preview.Builder().build().also { it.surfaceProvider = view.surfaceProvider }
                    provider.unbindAll()
                    provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, imageCapture)
                }, ContextCompat.getMainExecutor(ctx))
            } }, modifier = Modifier.fillMaxSize()
        )
        FloatingActionButton(
            onClick = {
                val raw = File(context.cacheDir, "capture-${System.nanoTime()}.jpg")
                imageCapture.takePicture(ImageCapture.OutputFileOptions.Builder(raw).build(), executor,
                    object : ImageCapture.OnImageSavedCallback {
                        override fun onImageSaved(result: ImageCapture.OutputFileResults) = onPhoto(raw)
                        override fun onError(exception: ImageCaptureException) { raw.delete() }
                    })
            }, modifier = Modifier.align(Alignment.BottomCenter).padding(24.dp), containerColor = androidx.compose.ui.graphics.Color.White
        ) { Icon(Icons.Default.CameraAlt, "撮影") }
    }
}

@Composable
private fun PendingPage(groups: List<SessionWithCaptures>, vm: ReceiptViewModel) {
    if (groups.isEmpty()) return Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("未送信の画像はありません") }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(groups, key = { it.session.id }) { group ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text(if (group.session.mode == CaptureMode.LONG_RECEIPT) "長いレシート ${group.captures.size}枚" else "レシート ${group.captures.size}枚")
                    Text(group.session.error ?: when (group.session.status) {
                        SessionStatus.UPLOADING -> "アップロード中"
                        SessionStatus.FAILED -> "送信失敗"
                        else -> "Wi-Fi待ち"
                    }, style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        TextButton({ vm.retry(group.session) }) { Text("再送") }
                        TextButton({ vm.discardPending(group) }) { Text("破棄") }
                    }
                }
            }
        }
    }
}

@Composable
private fun SettingsPage(initialPayer: String, folderName: String, onSave: (String) -> Unit, onConfigure: (String) -> Unit) {
    var payer by remember { mutableStateOf(initialPayer) }
    Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("設定", style = MaterialTheme.typography.headlineMedium)
        OutlinedTextField(payer, { payer = it }, Modifier.fillMaxWidth(), label = { Text("支払者名") })
        Text("保存先: $folderName")
        Button({ onSave(payer) }, enabled = payer.trim().isNotEmpty()) { Text("支払者名を保存") }
        OutlinedButton({ onConfigure(payer) }, enabled = payer.trim().isNotEmpty()) { Text("Googleアカウント・保存先を変更") }
    }
}
