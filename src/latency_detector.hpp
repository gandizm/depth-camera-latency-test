// SPDX-License-Identifier: Apache-2.0
// Derived from Intel RealSense librealsense rs-latency-tool (2017).
#pragma once

#include <librealsense2/rs.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include <opencv2/core.hpp>

namespace rs2_latency
{

struct latency_sample
{
    std::uint64_t sample = 0;
    std::uint64_t frame_number = 0;
    double frame_timestamp_ms = 0.0;
    std::string timestamp_domain;
    double visual_latency_ms = 0.0;
    double arrival_to_callback_ms = -1.0;
    double render_ms = 0.0;
};

class latency_detector
{
public:
    latency_detector(int digits, int display_width, std::string profile_description,
                     bool rotate_180);
    ~latency_detector();

    latency_detector(const latency_detector&) = delete;
    latency_detector& operator=(const latency_detector&) = delete;

    void submit_frame(rs2::frame frame);
    int next_value();
    void begin_render();
    void end_render();
    void copy_preview_to(cv::Mat& display);
    void write_csv(const std::string& path) const;
    void set_rotate_180(bool enabled);
    bool rotate_180() const;
    void set_collecting(bool enabled);

    std::size_t sample_count() const;
    double median_latency() const;
    double average_latency() const;
    std::uint64_t overwritten_frames() const;

private:
    struct record
    {
        rs2::frame frame;
        std::int64_t callback_elapsed_ms = 0;
        double arrival_to_callback_ms = -1.0;
    };

    void detect_loop();
    void request_new_value();
    void update_instructions();
    static cv::Mat frame_to_gray(const rs2::frame& frame);
    static double percentile(std::vector<double> values, double p);

    const int _digits;
    const int _modulus;
    const int _display_width;
    const cv::Size _preview_size;
    const std::string _profile_description;

    std::chrono::steady_clock::time_point _start_time;
    std::chrono::steady_clock::time_point _render_start;
    std::atomic_bool _alive{true};
    std::atomic_bool _new_value_requested{true};
    std::atomic<int> _current_value{0};
    std::atomic_bool _rotate_180{false};
    std::atomic<int> _detected_circles{0};
    std::atomic_bool _collecting{true};
    std::atomic<std::uint64_t> _overwritten_frames{0};

    mutable std::mutex _pending_mutex;
    std::condition_variable _pending_cv;
    std::optional<record> _pending;

    mutable std::mutex _data_mutex;
    std::deque<double> _latency_window;
    std::vector<latency_sample> _samples;
    double _latency_sum = 0.0;
    double _render_sum = 0.0;
    std::uint64_t _render_count = 0;

    mutable std::mutex _preview_mutex;
    cv::Mat _last_preview;
    cv::Mat _instructions;
    std::thread _worker;
};

}  // namespace rs2_latency
