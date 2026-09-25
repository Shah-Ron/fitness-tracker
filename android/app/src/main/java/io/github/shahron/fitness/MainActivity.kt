package io.github.shahron.fitness

import android.Manifest
import android.content.ContentValues
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Environment
import android.provider.MediaStore
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.webkit.WebViewAssetLoader
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * The whole app is the web page in assets. This activity gives it a secure
 * origin (https://appassets.androidplatform.net), the camera for barcode
 * scanning, a way to save backups into Downloads, and a native HTTP call for
 * Open Food Facts so the newer search service can be used.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private var pendingPermission: PermissionRequest? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)

        val s = web.settings
        s.javaScriptEnabled = true
        s.domStorageEnabled = true
        s.databaseEnabled = true
        s.mediaPlaybackRequiresUserGesture = false
        s.allowFileAccess = false
        s.allowContentAccess = false
        s.userAgentString = s.userAgentString + " FitnessTrackerApp/1.0"

        val loader = WebViewAssetLoader.Builder()
            .addPathHandler("/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()

        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                loader.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == "appassets.androidplatform.net") return false
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                if (!request.resources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) { request.deny(); return }
                if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                    request.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
                } else {
                    pendingPermission = request
                    ActivityCompat.requestPermissions(this@MainActivity, arrayOf(Manifest.permission.CAMERA), 1)
                }
            }
        }
        web.addJavascriptInterface(Bridge(), "Android")

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (web.canGoBack()) web.goBack() else finish()
            }
        })

        if (savedInstanceState == null) web.loadUrl("https://appassets.androidplatform.net/index.html")
        else web.restoreState(savedInstanceState)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val req = pendingPermission ?: return
        pendingPermission = null
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            req.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
        } else {
            req.deny()
        }
    }

    inner class Bridge {
        /** Keeps the screen on while a workout is open, so the rest timer is never missed. */
        @JavascriptInterface
        fun keepAwake(on: Boolean) {
            runOnUiThread {
                if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }

        /** Writes a backup or CSV into the phone's Downloads folder. */
        @JavascriptInterface
        fun saveFile(name: String, mime: String, text: String) {
            try {
                val values = ContentValues().apply {
                    put(MediaStore.Downloads.DISPLAY_NAME, name)
                    put(MediaStore.Downloads.MIME_TYPE, mime)
                    put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                    ?: throw IllegalStateException("Downloads folder not available")
                contentResolver.openOutputStream(uri)!!.use { it.write(text.toByteArray(Charsets.UTF_8)) }
                runOnUiThread { Toast.makeText(this@MainActivity, "Saved $name to Downloads", Toast.LENGTH_SHORT).show() }
            } catch (e: Exception) {
                runOnUiThread { Toast.makeText(this@MainActivity, "Could not save: ${e.message}", Toast.LENGTH_LONG).show() }
            }
        }

        /** Fetches JSON for the page (Open Food Facts), answering through window.__androidFetchDone. */
        @JavascriptInterface
        fun fetchJson(id: Int, url: String) {
            thread {
                var ok = false
                var payload: String
                try {
                    val c = URL(url).openConnection() as HttpURLConnection
                    c.connectTimeout = 8000
                    c.readTimeout = 12000
                    c.setRequestProperty("User-Agent", "FitnessTracker/1.0 (Android app, personal use)")
                    c.setRequestProperty("Accept", "application/json")
                    val code = c.responseCode
                    val body = (if (code < 400) c.inputStream else c.errorStream)?.bufferedReader()?.readText() ?: ""
                    payload = when {
                        code == 429 -> "Open Food Facts is rate limiting us. Try again in half a minute."
                        code == 404 -> { ok = true; "{\"status\":0}" }
                        code >= 500 -> "Open Food Facts is busy right now. Try again in a minute, or add the food yourself with New food."
                        code >= 400 -> "Open Food Facts answered $code."
                        else -> { ok = true; body }
                    }
                } catch (e: Exception) {
                    payload = "Could not reach Open Food Facts. Check the internet connection."
                }
                val js = "window.__androidFetchDone($id, $ok, ${JSONObject.quote(payload)})"
                runOnUiThread { web.evaluateJavascript(js, null) }
            }
        }
    }
}
