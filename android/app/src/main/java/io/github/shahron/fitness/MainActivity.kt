package io.github.shahron.fitness

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.MediaStore
import android.view.View
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
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.webkit.WebViewAssetLoader
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * The whole app is the web page in assets. This activity gives it a secure
 * origin (https://appassets.androidplatform.net), the camera for barcode
 * scanning, a way to save backups into Downloads, a native HTTP call for
 * Open Food Facts, haptics, the keep-screen-on flag, and a rest-timer alarm
 * that fires even when the screen is off.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private var pendingPermission: PermissionRequest? = null

    companion object {
        const val CHANNEL_REST = "rest"
        const val REQ_CAMERA = 1
        const val REQ_NOTIFY = 2
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        super.onCreate(savedInstanceState)
        web = WebView(this)
        setContentView(web)
        createChannels()

        val s = web.settings
        s.javaScriptEnabled = true
        s.domStorageEnabled = true
        s.databaseEnabled = true
        s.mediaPlaybackRequiresUserGesture = false
        s.allowFileAccess = false
        s.allowContentAccess = false
        s.userAgentString = s.userAgentString + " FitnessTrackerApp/1.0"
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isHapticFeedbackEnabled = true

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
                    ActivityCompat.requestPermissions(this@MainActivity, arrayOf(Manifest.permission.CAMERA), REQ_CAMERA)
                }
            }
        }
        web.addJavascriptInterface(Bridge(), "Android")

        // Back closes a sheet or returns to Today before it ever leaves the app.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                web.evaluateJavascript("(window.__androidBack ? window.__androidBack() : false)") { handled ->
                    if (handled != "true") {
                        if (web.canGoBack()) web.goBack() else moveTaskToBack(true)
                    }
                }
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
        if (requestCode != REQ_CAMERA) return
        val req = pendingPermission ?: return
        pendingPermission = null
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            req.grant(arrayOf(PermissionRequest.RESOURCE_VIDEO_CAPTURE))
        } else {
            req.deny()
        }
    }

    private fun createChannels() {
        val nm = getSystemService(NotificationManager::class.java)
        val ch = NotificationChannel(CHANNEL_REST, "Rest timer", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Tells you when the rest between sets is over"
            enableVibration(true)
            vibrationPattern = longArrayOf(0, 200, 100, 200)
        }
        nm.createNotificationChannel(ch)
    }

    private fun vibrator(): Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION") getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    private fun restPendingIntent(): PendingIntent =
        PendingIntent.getBroadcast(this, 7, Intent(this, RestAlarmReceiver::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    inner class Bridge {
        /** Keeps the screen on while a workout is open, so the rest timer is never missed. */
        @JavascriptInterface
        fun keepAwake(on: Boolean) {
            runOnUiThread {
                if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }

        /** Short, distinct vibrations: "light" for a tick, "heavy" for a phase change, "double" for a timer ending. */
        @JavascriptInterface
        fun haptic(kind: String) {
            val v = vibrator() ?: return
            val effect = when (kind) {
                "light" -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_CLICK)
                "heavy" -> VibrationEffect.createPredefined(VibrationEffect.EFFECT_HEAVY_CLICK)
                else -> VibrationEffect.createWaveform(longArrayOf(0, 200, 100, 200), -1)
            }
            v.vibrate(effect)
        }

        /** Asks for notification permission on Android 13 and later; earlier versions do not need it. */
        @JavascriptInterface
        fun requestNotifications() {
            if (Build.VERSION.SDK_INT < 33) return
            if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
            runOnUiThread { ActivityCompat.requestPermissions(this@MainActivity, arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIFY) }
        }

        /** An alarm at the given time that posts a rest-over notification, screen off or not. */
        @JavascriptInterface
        fun scheduleRest(atMillis: Long, label: String) {
            val am = getSystemService(AlarmManager::class.java)
            val intent = Intent(this@MainActivity, RestAlarmReceiver::class.java).putExtra("label", label)
            val pi = PendingIntent.getBroadcast(this@MainActivity, 7, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val exact = Build.VERSION.SDK_INT < Build.VERSION_CODES.S || am.canScheduleExactAlarms()
            if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, atMillis, pi)
        }

        @JavascriptInterface
        fun cancelRest() {
            getSystemService(AlarmManager::class.java).cancel(restPendingIntent())
            androidx.core.app.NotificationManagerCompat.from(this@MainActivity).cancel(RestAlarmReceiver.NOTIFY_ID)
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
