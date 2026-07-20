package jp.hirata.receiptcapture

import android.Manifest
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import androidx.compose.runtime.*
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    private val settings get() = ReceiptApplication.from(this).settings
    private var payerBeingConfigured = ""
    private var accountBeingConfigured = ""
    private var configurationRevision by mutableIntStateOf(0)
    private val authorizationClient by lazy { Identity.getAuthorizationClient(this) }

    private val authorizationLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult()
    ) { activityResult ->
        if (activityResult.resultCode == RESULT_OK && activityResult.data != null) {
            runCatching { authorizationClient.getAuthorizationResultFromIntent(activityResult.data!!) }
                .onSuccess(::finishPickerConfiguration)
                .onFailure { showConfigurationError("Google Driveの選択結果を読み取れませんでした", it) }
        } else {
            showConfigurationError("Google Driveフォルダの選択がキャンセルされました")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            registerForActivityResult(ActivityResultContracts.RequestPermission()) {}.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent {
            key(configurationRevision) {
                ReceiptCaptureApp(
                    configured = settings.configured,
                    initialPayer = settings.payer,
                    folderName = settings.folderName,
                    onConfigure = ::openFolderPicker,
                    onUpdatePayer = { settings.payer = it; configurationRevision++ },
                )
            }
        }
    }

    private fun openFolderPicker(payer: String) {
        payerBeingConfigured = payer.trim()
        if (payerBeingConfigured.isBlank()) return
        // Persist before opening Google Play services because the activity can be recreated
        // while the external Picker is in the foreground.
        settings.payer = payerBeingConfigured
        val request = AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(DriveAccess.DRIVE_FILE_SCOPE)))
            .setOptOutIncludingGrantedScopes(true)
            .setPrompt(AuthorizationRequest.Prompt.CONSENT or AuthorizationRequest.Prompt.SELECT_ACCOUNT)
            .addResourceParameter(AuthorizationRequest.ResourceParameter.PICKER_OAUTH_TRIGGER, "true")
            .addResourceParameter(AuthorizationRequest.ResourceParameter.PICKER_ALLOW_FOLDER_SELECTION, "true")
            .build()
        authorizationClient.authorize(request)
            .addOnSuccessListener { result ->
                accountBeingConfigured = result.toGoogleSignInAccount()?.email.orEmpty()
                if (result.hasResolution()) {
                    authorizationLauncher.launch(IntentSenderRequest.Builder(result.pendingIntent!!.intentSender).build())
                } else finishPickerConfiguration(result)
            }
            .addOnFailureListener { showConfigurationError("Google認証を開始できませんでした", it) }
    }

    private fun finishPickerConfiguration(result: AuthorizationResult) {
        val params = result.tokenResponseParams
        val folderIds = params?.get("picked_file_ids")?.toString().orEmpty()
        val folderId = folderIds.substringBefore(',').trim()
        val account = result.toGoogleSignInAccount()?.email.orEmpty()
            .ifBlank { accountBeingConfigured }
            .ifBlank { settings.accountName }
        Log.i(TAG, "Picker returned folder=${folderId.isNotBlank()}, account=${account.isNotBlank()}, keys=${params?.keySet()}")
        if (folderId.isBlank()) {
            showConfigurationError("フォルダIDを取得できませんでした。receipt-inboxを選択して「挿入」を押してください")
            return
        }
        val accessToken = result.accessToken.orEmpty()
        lifecycleScope.launch {
            val folderName = withContext(Dispatchers.IO) {
                runCatching {
                    val token = accessToken.ifBlank { DriveAccess.silentToken(applicationContext, account) }
                    token?.let { DriveFolderResolver(it).name(folderId) }
                }.getOrNull()
            } ?: AppSettings.UNKNOWN_FOLDER_NAME
            settings.payer = payerBeingConfigured.ifBlank { settings.payer }
            if (account.isNotBlank()) settings.accountName = account
            settings.folderId = folderId
            settings.folderName = folderName
            configurationRevision++
            Toast.makeText(this@MainActivity, "${folderName}を設定しました", Toast.LENGTH_SHORT).show()
            UploadWorker.enqueue(this@MainActivity, replace = true)
        }
    }

    private fun showConfigurationError(message: String, error: Throwable? = null) {
        Log.e(TAG, message, error)
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    companion object {
        private const val TAG = "ReceiptCaptureSetup"
    }
}
