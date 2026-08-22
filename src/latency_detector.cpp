// SPDX-License-Identifier: Apache-2.0
// Derived from Intel RealSense librealsense rs-latency-tool (2017).

#include "latency_detector.hpp"

#include <librealsense2/h/rs_internal.h>

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>

#include <opencv2/highgui.hpp>
#include <opencv2/imgproc.hpp>

namespace rs2_latency
{

namespace
{

bool unpack_value(const std::vector<bool>& bits, int* value)
{
    const auto on_bits = std::count(bits.begin() + 2, bits.end(), true);
    if ((on_bits % 2 == 1) != bits[0]
        || ((on_bits / 2) % 2 == 1) != bits[1]) return false;
    int result = 0;
    for (std::size_t index = 2; index < bits.size(); ++index)
        result = result * 2 + static_cast<int>(bits[index]);
    *value = result;
    return true;
}

double rs2_wall_time_ms()
{
    rs2_error* error = nullptr;
    const auto now = rs2_get_time(&error);
    if (error)
    {
        rs2_free_error(error);
        return -1.0;
    }
    return now;
}

}  // namespace

latency_detector::latency_detector(int digits, int display_width,
                                   std::string profile_description,
                                   bool rotate_180)
    : _digits(digits),
      _modulus(1 << (digits - 2)),
      _display_width(display_width),
      _preview_size(600, 350),
      _profile_description(std::move(profile_description)),
      _start_time(std::chrono::steady_clock::now()),
      _render_start(_start_time),
      _rotate_180(rotate_180),
      _last_preview(cv::Mat::zeros(_preview_size, CV_8UC1)),
      _instructions(cv::Mat::zeros(cv::Size(display_width, 145), CV_8UC1)),
      _worker([this]() { detect_loop(); })
{
    update_instructions();
}

void latency_detector::set_rotate_180(bool enabled)
{
    _rotate_180 = enabled;
    update_instructions();
}

bool latency_detector::rotate_180() const
{
    return _rotate_180.load();
}

void latency_detector::set_collecting(bool enabled)
{
    _collecting = enabled;
    update_instructions();
}

latency_detector::~latency_detector()
{
    _alive = false;
    _pending_cv.notify_all();
    if (_worker.joinable()) _worker.join();
}

void latency_detector::submit_frame(rs2::frame frame)
{
    record next;
    next.frame = std::move(frame);
    next.callback_elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - _start_time).count();

    if (next.frame.supports_frame_metadata(RS2_FRAME_METADATA_TIME_OF_ARRIVAL))
    {
        const auto now = rs2_wall_time_ms();
        if (now >= 0.0)
            next.arrival_to_callback_ms = now - next.frame.get_frame_metadata(
                RS2_FRAME_METADATA_TIME_OF_ARRIVAL);
    }

    {
        std::lock_guard<std::mutex> lock(_pending_mutex);
        if (_pending) ++_overwritten_frames;
        _pending = std::move(next);  // capacity one: newest frame always wins
    }
    _pending_cv.notify_one();
}

int latency_detector::next_value()
{
    if (_new_value_requested.exchange(false))
    {
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - _start_time).count();
        auto value = static_cast<int>(elapsed % _modulus);
        if (value == _current_value) value = (value + 1) % _modulus;
        _current_value = value;
    }
    return _current_value;
}

void latency_detector::begin_render()
{
    _render_start = std::chrono::steady_clock::now();
}

void latency_detector::end_render()
{
    const auto elapsed = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - _render_start).count();
    std::lock_guard<std::mutex> lock(_data_mutex);
    _render_sum += elapsed;
    ++_render_count;
}

void latency_detector::copy_preview_to(cv::Mat& display)
{
    std::lock_guard<std::mutex> lock(_preview_mutex);
    const cv::Rect preview_roi(
        cv::Point(_display_width / 2 - _preview_size.width / 2, 200),
        _last_preview.size());
    _last_preview.copyTo(display(preview_roi));
    const cv::Rect text_roi(cv::Point(0, 565), _instructions.size());
    _instructions.copyTo(display(text_roi));
}

std::size_t latency_detector::sample_count() const
{
    std::lock_guard<std::mutex> lock(_data_mutex);
    return _samples.size();
}

double latency_detector::median_latency() const
{
    std::lock_guard<std::mutex> lock(_data_mutex);
    std::vector<double> values;
    values.reserve(_samples.size());
    for (const auto& sample : _samples)
        values.push_back(sample.visual_latency_ms);
    return percentile(std::move(values), 0.5);
}

double latency_detector::average_latency() const
{
    std::lock_guard<std::mutex> lock(_data_mutex);
    return _samples.empty() ? 0.0 : _latency_sum / _samples.size();
}

std::uint64_t latency_detector::overwritten_frames() const
{
    return _overwritten_frames.load();
}

double latency_detector::percentile(std::vector<double> values, double p)
{
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    const auto index = static_cast<std::size_t>(
        std::round((values.size() - 1) * std::clamp(p, 0.0, 1.0)));
    return values[index];
}

cv::Mat latency_detector::frame_to_gray(const rs2::frame& frame)
{
    auto video = frame.as<rs2::video_frame>();
    if (!video) throw std::runtime_error("Latency detector needs a video frame");
    const cv::Size size(video.get_width(), video.get_height());
    cv::Mat gray;
    switch (frame.get_profile().format())
    {
        case RS2_FORMAT_Y8:
            gray = cv::Mat(size, CV_8UC1, const_cast<void*>(frame.get_data()),
                           video.get_stride_in_bytes()).clone();
            break;
        case RS2_FORMAT_YUYV:
        {
            cv::Mat yuyv(size, CV_8UC2, const_cast<void*>(frame.get_data()),
                         video.get_stride_in_bytes());
            cv::cvtColor(yuyv, gray, cv::COLOR_YUV2GRAY_YUY2);
            break;
        }
        case RS2_FORMAT_BGR8:
        {
            cv::Mat bgr(size, CV_8UC3, const_cast<void*>(frame.get_data()),
                        video.get_stride_in_bytes());
            cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);
            break;
        }
        case RS2_FORMAT_RGB8:
        {
            cv::Mat rgb(size, CV_8UC3, const_cast<void*>(frame.get_data()),
                        video.get_stride_in_bytes());
            cv::cvtColor(rgb, gray, cv::COLOR_RGB2GRAY);
            break;
        }
        default:
            throw std::runtime_error("Selected frame format is not supported");
    }
    return gray;
}

void latency_detector::request_new_value()
{
    _new_value_requested = true;
}

void latency_detector::detect_loop()
{
    while (_alive)
    {
        record current;
        {
            std::unique_lock<std::mutex> lock(_pending_mutex);
            _pending_cv.wait_for(lock, std::chrono::milliseconds(50),
                [this]() { return !_alive || _pending.has_value(); });
            if (!_alive) break;
            if (!_pending) continue;
            current = std::move(*_pending);
            _pending.reset();
        }

        bool keep_current_pattern = false;
        try
        {
            auto gray = frame_to_gray(current.frame);
            if (_rotate_180.load()) cv::rotate(gray, gray, cv::ROTATE_180);
            cv::medianBlur(gray, gray, 5);
            std::vector<cv::Vec3f> circles;
            cv::HoughCircles(gray, circles, cv::HOUGH_GRADIENT,
                             1, 10, 100, 30, 1, 100);

            // The official sample searches only the top quarter of the image.
            // For a robot-mounted or upside-down camera, select the row with
            // the most circles and widest horizontal span anywhere in-frame.
            std::vector<cv::Vec3f> selected_circles;
            double best_score = -1.0;
            const auto y_tolerance = std::max(20.0f, gray.rows * 0.10f);
            for (const auto& anchor : circles)
            {
                std::vector<cv::Vec3f> row;
                for (const auto& candidate : circles)
                {
                    if (std::abs(candidate[1] - anchor[1]) <= y_tolerance)
                        row.push_back(candidate);
                }
                if (row.size() < 2) continue;
                const auto minmax = std::minmax_element(row.begin(), row.end(),
                    [](const cv::Vec3f& left, const cv::Vec3f& right)
                    { return left[0] < right[0]; });
                const auto span = (*minmax.second)[0] - (*minmax.first)[0];
                const auto score = row.size() * 10000.0 + span;
                if (score > best_score)
                {
                    best_score = score;
                    selected_circles = std::move(row);
                }
            }
            std::sort(selected_circles.begin(), selected_circles.end(),
                [](const cv::Vec3f& left, const cv::Vec3f& right)
                { return left[0] < right[0]; });
            _detected_circles = static_cast<int>(selected_circles.size());

            auto annotated = gray.clone();
            for (const auto& circle : selected_circles)
            {
                const int radius = static_cast<int>(circle[2]);
                cv::rectangle(annotated,
                    cv::Rect(static_cast<int>(circle[0]) - radius - 5,
                             static_cast<int>(circle[1]) - radius - 5,
                             2 * radius + 10, 2 * radius + 10),
                    cv::Scalar(96), -1, cv::LINE_AA);
            }
            cv::resize(annotated, annotated, _preview_size);
            {
                std::lock_guard<std::mutex> lock(_preview_mutex);
                _last_preview = std::move(annotated);
            }

            if (selected_circles.size() > 1)
            {
                int min_x = static_cast<int>(selected_circles.front()[0]);
                int max_x = static_cast<int>(selected_circles.back()[0]);
                const int spacing = (max_x - min_x) / (_digits + 1);
                min_x += spacing / 2;
                max_x -= spacing / 2;
                std::vector<bool> bits(_digits, false);
                if (max_x > min_x)
                {
                    for (std::size_t index = 1;
                         index + 1 < selected_circles.size(); ++index)
                    {
                        const auto x = static_cast<int>(selected_circles[index][0]);
                        const auto bit = static_cast<int>(_digits
                            * (static_cast<double>(x - min_x) / (max_x - min_x)));
                        if (bit >= 0 && bit < _digits) bits[bit] = true;
                    }
                    int decoded = 0;
                    if (unpack_value(bits, &decoded))
                    {
                        if (decoded == _current_value)
                        {
                            const int callback_clock = static_cast<int>(
                                current.callback_elapsed_ms % _modulus);
                            const int delta = (callback_clock - decoded + _modulus)
                                % _modulus;
                            double render_average = 0.0;
                            {
                                std::lock_guard<std::mutex> lock(_data_mutex);
                                render_average = _render_count
                                    ? _render_sum / _render_count : 0.0;
                            }
                            const auto visual_latency = delta - render_average;
                            if (_collecting.load() && visual_latency >= 0.0
                                && visual_latency < 2000.0)
                            {
                                latency_sample sample;
                                sample.frame_number = current.frame.get_frame_number();
                                sample.frame_timestamp_ms = current.frame.get_timestamp();
                                sample.timestamp_domain = rs2_timestamp_domain_to_string(
                                    current.frame.get_frame_timestamp_domain());
                                sample.visual_latency_ms = visual_latency;
                                sample.arrival_to_callback_ms =
                                    current.arrival_to_callback_ms;
                                sample.render_ms = render_average;
                                {
                                    std::lock_guard<std::mutex> lock(_data_mutex);
                                    sample.sample = _samples.size() + 1;
                                    _samples.push_back(sample);
                                    _latency_sum += visual_latency;
                                    _latency_window.push_back(visual_latency);
                                    if (_latency_window.size() > 31)
                                        _latency_window.pop_front();
                                }
                                update_instructions();
                            }
                        }
                        else
                        {
                            // A valid older pattern is still in flight. Keep the
                            // current pattern stable until it reaches the camera.
                            keep_current_pattern = true;
                        }
                    }
                }
            }
        }
        catch (const std::exception& error)
        {
            std::cerr << "Detector warning: " << error.what() << "\n";
        }

        if (!keep_current_pattern) request_new_value();
    }
}

void latency_detector::update_instructions()
{
    std::vector<double> values;
    double average = 0.0;
    std::size_t count = 0;
    double arrival = -1.0;
    {
        std::lock_guard<std::mutex> lock(_data_mutex);
        values.reserve(_latency_window.size());
        for (auto value : _latency_window) values.push_back(value);
        count = _samples.size();
        average = count ? _latency_sum / count : 0.0;
        if (!_samples.empty()) arrival = _samples.back().arrival_to_callback_ms;
    }

    cv::Mat panel = cv::Mat::zeros(cv::Size(_display_width, 145), CV_8UC1);
    const auto draw = [&](const std::string& text, int y, double scale = 0.67)
    {
        cv::putText(panel, text, cv::Point(30, y), cv::FONT_HERSHEY_SIMPLEX,
                    scale, cv::Scalar(255), 2, cv::LINE_AA);
    };
    draw(_profile_description, 24, 0.55);
    draw("Point the camera at all circles. Q/Esc exits; F fullscreen; R rotates 180 deg.",
         57, 0.58);
    std::ostringstream latency;
    latency << std::fixed << std::setprecision(1)
            << "samples=" << count
            << "  visual median=" << percentile(values, 0.5) << " ms"
            << "  p95=" << percentile(values, 0.95) << " ms"
            << "  average=" << average << " ms";
    draw(latency.str(), 94);
    std::ostringstream transport;
    transport << std::fixed << std::setprecision(2)
              << "arrival->callback=";
    if (arrival >= 0.0) transport << arrival << " ms";
    else transport << "metadata unavailable";
    transport << "  overwritten latest-only frames=" << _overwritten_frames.load();
    transport << "  circles=" << _detected_circles.load();
    transport << "  rotate=" << (_rotate_180.load() ? 180 : 0);
    transport << "  phase=" << (_collecting.load() ? "measure" : "warmup");
    draw(transport.str(), 131, 0.62);

    std::lock_guard<std::mutex> lock(_preview_mutex);
    _instructions = std::move(panel);
}

void latency_detector::write_csv(const std::string& path) const
{
    if (path.empty()) return;
    std::vector<latency_sample> samples;
    {
        std::lock_guard<std::mutex> lock(_data_mutex);
        samples = _samples;
    }
    std::ofstream output(path);
    if (!output) throw std::runtime_error("Cannot write CSV: " + path);
    output << "sample,profile,frame_number,frame_timestamp_ms,timestamp_domain,"
              "visual_latency_ms,arrival_to_callback_ms,render_ms\n";
    output << std::fixed << std::setprecision(3);
    for (const auto& sample : samples)
    {
        output << sample.sample << ',' << _profile_description << ','
               << sample.frame_number << ','
               << sample.frame_timestamp_ms << ',' << sample.timestamp_domain << ','
               << sample.visual_latency_ms << ',' << sample.arrival_to_callback_ms
               << ',' << sample.render_ms << '\n';
    }
}

}  // namespace rs2_latency
