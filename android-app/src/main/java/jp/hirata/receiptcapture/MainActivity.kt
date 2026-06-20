package jp.hirata.receiptcapture

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope

class MainActivity : ComponentActivity() {
    private val settings get() = ReceiptApplication.from(this).settings
    private var payerBeingConfigured = ""
    private var configurationRevision by mutableIntStateOf(0)
    private val authorizationClient by lazy { Identity.getAuthorizationClient(this) }

    private val authorizationLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult()
    ) { activityResult ->
        if (activityResult.resultCode == RESULT_OK && activityResult.data != null) {
            runCatching { authorizationClient.getAuthorizationResultFromIntent(activityResult.data!!) }
                .onSuccess(::finishPickerConfiguration)
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
        val request = AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(DriveAccess.DRIVE_FILE_SCOPE)))
            .setOptOutIncludingGrantedScopes(true)
            .setPrompt(AuthorizationRequest.Prompt.CONSENT or AuthorizationRequest.Prompt.SELECT_ACCOUNT)
            .addResourceParameter(AuthorizationRequest.ResourceParameter.PICKER_OAUTH_TRIGGER, "true")
            .addResourceParameter(AuthorizationRequest.ResourceParameter.PICKER_ALLOW_FOLDER_SELECTION, "true")
            .build()
        authorizationClient.authorize(request)
            .addOnSuccessListener { result ->
                if (result.hasResolution()) {
                    authorizationLauncher.launch(IntentSenderRequest.Builder(result.pendingIntent!!.intentSender).build())
                } else finishPickerConfiguration(result)
            }
    }

    private fun finishPickerConfiguration(result: AuthorizationResult) {
        val folderIds = result.tokenResponseParams?.getString("picked_file_ids").orEmpty()
        val folderId = folderIds.substringBefore(',').trim()
        val account = result.toGoogleSignInAccount()?.email.orEmpty()
        if (folderId.isBlank() || account.isBlank()) return
        settings.payer = payerBeingConfigured.ifBlank { settings.payer }
        settings.accountName = account
        settings.folderId = folderId
        settings.folderName = "receipt-inbox"
        configurationRevision++
        UploadWorker.enqueue(this, replace = true)
    }
}
