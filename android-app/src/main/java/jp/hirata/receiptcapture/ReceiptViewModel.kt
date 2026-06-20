package jp.hirata.receiptcapture

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import jp.hirata.receiptcapture.data.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import java.io.File
import java.util.UUID

data class ReceiptUiState(
    val draft: SessionWithCaptures? = null,
    val pending: List<SessionWithCaptures> = emptyList(),
    val takingPhoto: Boolean = true,
    val busy: Boolean = false,
    val message: String? = null,
)

class ReceiptViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ReceiptApplication
    private val dao = app.database.dao()
    private val local = MutableStateFlow(ReceiptUiState())
    val state = combine(dao.observeDraft(), dao.observePending(), local) { draft, pending, ui ->
        ui.copy(draft = draft?.copy(captures = draft.captures.sortedBy { it.position }), pending = pending)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ReceiptUiState())

    fun setMode(mode: CaptureMode) = viewModelScope.launch {
        val current = state.value.draft
        if (current == null) dao.insertSession(SessionEntity(UUID.randomUUID().toString(), mode))
        else if (current.captures.isEmpty()) dao.updateSession(current.session.copy(mode = mode))
    }

    fun photoSaved(raw: File) = viewModelScope.launch {
        update(busy = true)
        try {
            var draft = state.value.draft
            if (draft == null) {
                val session = SessionEntity(UUID.randomUUID().toString(), CaptureMode.MULTIPLE_RECEIPTS)
                dao.insertSession(session)
                draft = SessionWithCaptures(session, emptyList())
            }
            val id = UUID.randomUUID().toString()
            val target = File(app.filesDir, "captures/${draft.session.id}/$id.jpg")
            ImageFiles.normalize(raw, target)
            raw.delete()
            dao.insertCapture(CaptureEntity(id, draft.session.id, draft.captures.size, target.path))
            update(takingPhoto = false)
        } catch (error: Exception) {
            raw.delete(); update(message = error.message ?: "撮影画像を保存できません")
        } finally { update(busy = false) }
    }

    fun nextPhoto() = update(takingPhoto = true)

    fun discardLast() = viewModelScope.launch {
        val capture = state.value.draft?.captures?.maxByOrNull { it.position } ?: return@launch
        File(capture.path).delete(); dao.deleteCapture(capture)
        if (state.value.draft?.captures?.size == 1) update(takingPhoto = true)
    }

    fun discardAll() = viewModelScope.launch {
        state.value.draft?.let { group ->
            group.captures.forEach { File(it.path).delete() }
            dao.deleteSession(group.session)
        }
        update(takingPhoto = true)
    }

    fun queueUpload() = viewModelScope.launch {
        val group = state.value.draft ?: return@launch
        if (group.captures.isEmpty()) return@launch
        dao.updateSession(group.session.copy(status = SessionStatus.QUEUED, payer = app.settings.payer, error = null))
        update(takingPhoto = true, message = "Wi-Fi接続時にアップロードします")
        UploadWorker.enqueue(app)
    }

    fun retry(session: SessionEntity) = viewModelScope.launch {
        dao.updateSession(session.copy(status = SessionStatus.QUEUED, error = null))
        UploadWorker.enqueue(app, replace = true)
    }

    fun discardPending(group: SessionWithCaptures) = viewModelScope.launch {
        group.captures.forEach { File(it.path).delete() }
        File(app.filesDir, "uploads/${group.session.id}.jpg").delete()
        dao.deleteSession(group.session)
    }

    fun clearMessage() = update(message = null)
    private fun update(
        takingPhoto: Boolean = local.value.takingPhoto,
        busy: Boolean = local.value.busy,
        message: String? = local.value.message,
    ) { local.value = local.value.copy(takingPhoto = takingPhoto, busy = busy, message = message) }
}
