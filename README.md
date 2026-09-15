# afit-biometric-attendance-staff

Attendance is captured locally before it is submitted to the API. The client
stores a durable queue in `attendance_queue.db`, including the local UTC+1
capture date and time. If the API is offline, queued events are retried at
startup and after each scan.

Only events captured in the current month are retained or submitted. Older
queued events are discarded, and successfully submitted events are deleted from
the local queue.
# afit-biometric-attendance-staff
