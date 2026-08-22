// SPDX-License-Identifier: Apache-2.0
// Multi-device extension of Intel RealSense librealsense rs-latency-tool.

#include "device_profiles.hpp"
#include "latency_detector.hpp"

#include <librealsense2/rs.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <opencv2/highgui.hpp>
#include <opencv2/imgproc.hpp>

namespace
{

struct options
{
    rs2_latency::profile_request profile;
    rs2_latency::depth_request depth;
    bool list = false;
    bool fullscreen = false;
    bool topmost = true;
    bool rotate_180 = false;
    int duration_seconds = 0;
    int warmup_seconds = 0;
    std::string csv_path;
};

std::atomic_bool running{true};

void on_signal(int)
{
    running = false;
}

void print_help(const char* program)
{
    std::cout
        << "Usage: " << program << " [options]\n\n"
        << "Device/profile selection:\n"
        << "  --list                    list compatible profiles and exit\n"
        << "  --serial SERIAL           select a device by serial number\n"
        << "  --device-index N          select device N (default: 0)\n"
        << "  --stream auto|color|infrared (default: auto, prefers color)\n"
        << "  --stream-index N          select indexed infrared stream\n"
        << "  --width N --height N --fps N\n"
        << "  --format auto|yuyv|bgr8|rgb8|y8\n"
        << "  --policy low-latency|quality (default: low-latency)\n\n"
        << "Auxiliary load:\n"
        << "  --with-depth              require depth (default: prefer 640x480@90)\n"
        << "  --no-depth                disable the default depth stream\n"
        << "  --depth-width N --depth-height N --depth-fps N\n\n"
        << "Window/output:\n"
        << "  --fullscreen              start fullscreen (default: visible window)\n"
        << "  --no-topmost              do not request an always-on-top window\n"
        << "  --rotate 0|180            rotate capture, preview and detection\n"
        << "  --duration SECONDS        stop automatically; 0 means until Q/Esc\n"
        << "  --warmup SECONDS          detect but discard samples before measuring\n"
        << "  --csv PATH                write accepted samples to CSV on exit\n"
        << "  --help                    show this text\n\n"
        << "Runtime keys: F toggles fullscreen; R rotates 180; Q or Esc exits.\n";
}

int parse_int(const std::string& name, const std::string& value)
{
    try
    {
        std::size_t consumed = 0;
        const auto result = std::stoi(value, &consumed);
        if (consumed != value.size()) throw std::invalid_argument("trailing text");
        return result;
    }
    catch (const std::exception&)
    {
        throw std::runtime_error(name + " requires an integer, got: " + value);
    }
}

options parse_options(int argc, char** argv)
{
    options result;
    const auto value_after = [&](int* index, const std::string& option)
    {
        if (*index + 1 >= argc) throw std::runtime_error(option + " needs a value");
        return std::string(argv[++(*index)]);
    };

    for (int index = 1; index < argc; ++index)
    {
        const std::string argument(argv[index]);
        if (argument == "--help" || argument == "-h")
        {
            print_help(argv[0]);
            std::exit(EXIT_SUCCESS);
        }
        else if (argument == "--list") result.list = true;
        else if (argument == "--fullscreen") result.fullscreen = true;
        else if (argument == "--no-topmost") result.topmost = false;
        else if (argument == "--rotate")
        {
            const auto degrees = parse_int(argument, value_after(&index, argument));
            if (degrees != 0 && degrees != 180)
                throw std::runtime_error("--rotate must be 0 or 180");
            result.rotate_180 = degrees == 180;
        }
        else if (argument == "--serial")
            result.profile.serial = value_after(&index, argument);
        else if (argument == "--device-index")
            result.profile.device_index = parse_int(argument, value_after(&index, argument));
        else if (argument == "--stream")
            result.profile.stream = value_after(&index, argument);
        else if (argument == "--stream-index")
            result.profile.stream_index = parse_int(argument, value_after(&index, argument));
        else if (argument == "--width")
            result.profile.width = parse_int(argument, value_after(&index, argument));
        else if (argument == "--height")
            result.profile.height = parse_int(argument, value_after(&index, argument));
        else if (argument == "--fps")
            result.profile.fps = parse_int(argument, value_after(&index, argument));
        else if (argument == "--format")
            result.profile.format = value_after(&index, argument);
        else if (argument == "--policy")
            result.profile.policy = value_after(&index, argument);
        else if (argument == "--with-depth")
        {
            result.depth.enabled = true;
            result.depth.required = true;
        }
        else if (argument == "--no-depth") result.depth.enabled = false;
        else if (argument == "--depth-width")
        {
            result.depth.enabled = true;
            result.depth.required = true;
            result.depth.width_explicit = true;
            result.depth.width = parse_int(argument, value_after(&index, argument));
        }
        else if (argument == "--depth-height")
        {
            result.depth.enabled = true;
            result.depth.required = true;
            result.depth.height_explicit = true;
            result.depth.height = parse_int(argument, value_after(&index, argument));
        }
        else if (argument == "--depth-fps")
        {
            result.depth.enabled = true;
            result.depth.required = true;
            result.depth.fps_explicit = true;
            result.depth.fps = parse_int(argument, value_after(&index, argument));
        }
        else if (argument == "--duration")
            result.duration_seconds = parse_int(argument, value_after(&index, argument));
        else if (argument == "--warmup")
            result.warmup_seconds = parse_int(argument, value_after(&index, argument));
        else if (argument == "--csv")
            result.csv_path = value_after(&index, argument);
        else
            throw std::runtime_error("Unknown option: " + argument);
    }
    return result;
}

std::vector<bool> pack_value(int value, int digits)
{
    std::vector<bool> bits(digits, false);
    for (int index = digits - 1; index >= 2; --index)
    {
        bits[index] = (value & 1) != 0;
        value >>= 1;
    }
    const auto on_bits = std::count(bits.begin() + 2, bits.end(), true);
    bits[0] = on_bits % 2 == 1;
    bits[1] = (on_bits / 2) % 2 == 1;
    return bits;
}

void set_fullscreen(const std::string& window, bool enabled)
{
    cv::setWindowProperty(window, cv::WND_PROP_FULLSCREEN,
        enabled ? cv::WINDOW_FULLSCREEN : cv::WINDOW_NORMAL);
}

void set_latest_queue(rs2::sensor& sensor, const std::string& label)
{
    if (sensor.supports(RS2_OPTION_FRAMES_QUEUE_SIZE))
    {
        const auto range = sensor.get_option_range(RS2_OPTION_FRAMES_QUEUE_SIZE);
        const auto queue_size = std::clamp(1.0f, range.min, range.max);
        sensor.set_option(RS2_OPTION_FRAMES_QUEUE_SIZE, queue_size);
        std::cout << "QUEUE_SIZE " << label << '=' << queue_size << "\n";
    }
    else
    {
        std::cout << "QUEUE_SIZE " << label
                  << " sensor option unavailable; application queue remains 1\n";
    }
}

}  // namespace

int main(int argc, char** argv) try
{
    const auto arguments = parse_options(argc, argv);
    rs2::context context;
    auto devices = context.query_devices();
    if (arguments.list)
    {
        rs2_latency::print_devices(devices, std::cout);
        return EXIT_SUCCESS;
    }

    auto selected = rs2_latency::choose_profile(devices, arguments.profile);
    auto description = rs2_latency::describe(selected);
    std::cout << "SELECTED " << description << "\n";
    set_latest_queue(selected.sensor, "visual");

    std::optional<rs2_latency::selected_profile> depth;
    if (arguments.depth.enabled)
    {
        try
        {
            depth = rs2_latency::choose_depth_profile(
                selected.device, arguments.depth, selected.profile);
        }
        catch (const std::runtime_error& error)
        {
            if (arguments.depth.required) throw;
            std::cerr << "DEFAULT_DEPTH_SKIPPED " << error.what() << "\n";
        }
    }
    if (depth)
    {
        const auto& profile = depth->profile;
        std::ostringstream depth_text;
        depth_text << "Depth[" << profile.stream_index() << "] "
                   << profile.width() << 'x' << profile.height() << '@'
                   << profile.fps() << ' ' << rs2_format_to_string(profile.format());
        std::cout << "AUXILIARY " << depth_text.str() << "\n";
        description += " + " + depth_text.str();
        if (depth->sensor.get().get() != selected.sensor.get().get())
            set_latest_queue(depth->sensor, "depth");
    }

    constexpr int display_width = 1280;
    constexpr int display_height = 720;
    constexpr int digits = 16;
    constexpr const char* window_name = "RealSense Latency Lab";
    rs2_latency::latency_detector detector(
        digits, display_width, description, arguments.rotate_180);
    std::atomic<std::uint64_t> captured_frames{0};
    std::atomic<std::int64_t> first_callback_ns{0};
    std::atomic<std::int64_t> last_callback_ns{0};
    std::atomic<std::uint64_t> depth_frames{0};
    std::atomic<std::int64_t> depth_first_ns{0};
    std::atomic<std::int64_t> depth_last_ns{0};

    bool opened = false;
    bool started = false;
    bool depth_opened = false;
    bool depth_started = false;
    const bool shared_sensor = depth
        && depth->sensor.get().get() == selected.sensor.get().get();

    const auto visual_callback = [&](rs2::frame frame)
    {
        const auto now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        if (frame.get_profile().stream_type() == RS2_STREAM_DEPTH)
        {
            std::int64_t unset = 0;
            depth_first_ns.compare_exchange_strong(unset, now_ns);
            depth_last_ns = now_ns;
            ++depth_frames;
            return;
        }
        std::int64_t unset = 0;
        first_callback_ns.compare_exchange_strong(unset, now_ns);
        last_callback_ns = now_ns;
        ++captured_frames;
        detector.submit_frame(std::move(frame));
    };
    try
    {
        if (shared_sensor)
            selected.sensor.open(std::vector<rs2::stream_profile>{
                selected.profile, depth->profile});
        else
            selected.sensor.open(selected.profile);
        opened = true;
        if (depth && !shared_sensor)
        {
            depth->sensor.open(depth->profile);
            depth_opened = true;
        }
        selected.sensor.start(visual_callback);
        started = true;
        if (depth && !shared_sensor)
        {
            depth->sensor.start(visual_callback);
            depth_started = true;
        }

        cv::namedWindow(window_name, cv::WINDOW_NORMAL);
        cv::resizeWindow(window_name, display_width, display_height);
        cv::moveWindow(window_name, 40, 40);
        if (arguments.topmost)
        {
            try
            {
                cv::setWindowProperty(window_name, cv::WND_PROP_TOPMOST, 1);
            }
            catch (const cv::Exception&)
            {
                std::cerr << "Window manager does not support WND_PROP_TOPMOST\n";
            }
        }
        set_fullscreen(window_name, arguments.fullscreen);
        std::cout << "WINDOW_READY title=\"" << window_name
                  << "\" mode=" << (arguments.fullscreen ? "fullscreen" : "windowed")
                  << " rotate=" << (arguments.rotate_180 ? 180 : 0)
                  << " keys=F,R,Q,Esc\n";

        std::signal(SIGINT, on_signal);
        std::signal(SIGTERM, on_signal);
        bool fullscreen = arguments.fullscreen;
        const auto run_started = std::chrono::steady_clock::now();
        bool measuring = arguments.warmup_seconds == 0;
        detector.set_collecting(measuring);

        while (running)
        {
            detector.begin_render();
            cv::Mat display = cv::Mat::zeros(display_height, display_width, CV_8UC3);
            detector.copy_preview_to(display);

            const auto bits = pack_value(detector.next_value(), digits);
            const int circle_width = (display_width - 120) / (digits + 2);
            for (int index = 0; index < digits + 2; ++index)
            {
                const int radius = circle_width / 2 - 6;
                if (index == 0 || index == digits + 1 || bits[index - 1])
                {
                    cv::circle(display,
                        cv::Point(50 + circle_width * index + radius, 70 + radius),
                        radius, cv::Scalar(255, 255, 255), -1, cv::LINE_AA);
                }
            }

            cv::imshow(window_name, display);
            const int key = cv::waitKey(1) & 0xff;
            detector.end_render();
            if (key == 'q' || key == 'Q' || key == 27) break;
            if (key == 'f' || key == 'F')
            {
                fullscreen = !fullscreen;
                set_fullscreen(window_name, fullscreen);
            }
            if (key == 'r' || key == 'R')
                detector.set_rotate_180(!detector.rotate_180());
            const auto elapsed = std::chrono::steady_clock::now() - run_started;
            if (!measuring
                && elapsed >= std::chrono::seconds(arguments.warmup_seconds))
            {
                measuring = true;
                detector.set_collecting(true);
                std::cout << "MEASUREMENT_STARTED warmup="
                          << arguments.warmup_seconds << "s\n";
            }
            // GTK3 under GNOME Wayland/XWayland may report -1 for an
            // unsupported visibility property. Only an explicit zero means
            // the user closed the window.
            if (cv::getWindowProperty(window_name, cv::WND_PROP_VISIBLE) == 0) break;
            if (arguments.duration_seconds > 0
                && elapsed >= std::chrono::seconds(
                    arguments.warmup_seconds + arguments.duration_seconds)) break;
        }
    }
    catch (...)
    {
        if (depth_started) depth->sensor.stop();
        if (started) selected.sensor.stop();
        if (depth_opened) depth->sensor.close();
        if (opened) selected.sensor.close();
        cv::destroyAllWindows();
        throw;
    }

    if (depth_started) depth->sensor.stop();
    if (started) selected.sensor.stop();
    if (depth_opened) depth->sensor.close();
    if (opened) selected.sensor.close();
    cv::destroyAllWindows();
    detector.write_csv(arguments.csv_path);

    double capture_rate = 0.0;
    const auto captured = captured_frames.load();
    const auto first_ns = first_callback_ns.load();
    const auto last_ns = last_callback_ns.load();
    if (captured > 1 && last_ns > first_ns)
        capture_rate = (captured - 1) * 1e9 / (last_ns - first_ns);
    double depth_rate = 0.0;
    const auto depth_captured = depth_frames.load();
    const auto depth_first = depth_first_ns.load();
    const auto depth_last = depth_last_ns.load();
    if (depth_captured > 1 && depth_last > depth_first)
        depth_rate = (depth_captured - 1) * 1e9 / (depth_last - depth_first);

    std::cout << std::fixed << std::setprecision(2)
              << "SUMMARY captured_frames=" << captured
              << " capture_fps=" << capture_rate
              << " samples=" << detector.sample_count()
              << " median_ms=" << detector.median_latency()
              << " average_ms=" << detector.average_latency()
              << " overwritten_frames=" << detector.overwritten_frames();
    if (depth)
        std::cout << " depth_frames=" << depth_captured
                  << " depth_fps=" << depth_rate;
    std::cout << "\n";
    if (!arguments.csv_path.empty())
        std::cout << "CSV " << arguments.csv_path << "\n";
    return EXIT_SUCCESS;
}
catch (const rs2::error& error)
{
    std::cerr << "RealSense error calling " << error.get_failed_function()
              << '(' << error.get_failed_args() << "): " << error.what() << "\n";
    return EXIT_FAILURE;
}
catch (const std::exception& error)
{
    std::cerr << "Error: " << error.what() << "\n";
    return EXIT_FAILURE;
}
