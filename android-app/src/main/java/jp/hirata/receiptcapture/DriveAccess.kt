package jp.hirata.receiptcapture

import android.accounts.Account
import android.content.Context
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.gms.tasks.Tasks

object DriveAccess {
    const val DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"

    fun basicRequest(accountName: String): AuthorizationRequest {
        val builder = AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(DRIVE_FILE_SCOPE)))
        if (accountName.isNotBlank()) {
            builder.setAccount(Account(accountName, "com.google"))
        }
        return builder.build()
    }

    fun silentToken(context: Context, accountName: String): String? {
        val result = Tasks.await(Identity.getAuthorizationClient(context).authorize(basicRequest(accountName)))
        return if (result.hasResolution()) null else result.accessToken
    }
}
