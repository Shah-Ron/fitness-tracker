package io.github.shahron.fitness

import android.Manifest
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/** Fires when a rest period ends while the app is not in front: buzzes and shows a notification. */
class RestAlarmReceiver : BroadcastReceiver() {
    companion object {
        const val NOTIFY_ID = 1001
    }

    override fun onReceive(context: Context, intent: Intent) {
        val label = intent.getStringExtra("label") ?: "Next set"
        val open = PendingIntent.getActivity(
            context, 0, Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val n = NotificationCompat.Builder(context, MainActivity.CHANNEL_REST)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle("Rest over")
            .setContentText(label)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setVibrate(longArrayOf(0, 200, 100, 200))
            .setDefaults(NotificationCompat.DEFAULT_SOUND)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        try {
            NotificationManagerCompat.from(context).notify(NOTIFY_ID, n)
        } catch (e: SecurityException) {
            // Notifications were switched off for the app; nothing more to do.
        }
    }
}
