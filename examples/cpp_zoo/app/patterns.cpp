#include "patterns.hpp"

#include <algorithm>

namespace zoo::app {

std::map<std::string, PluginRegistry::Creator> PluginRegistry::creators_;

void QuickSort::sort(std::vector<int>& data) { std::sort(data.begin(), data.end()); }
void MergeSort::sort(std::vector<int>& data) { std::stable_sort(data.begin(), data.end()); }

void Red::next(TrafficLight& light) { light.setState(std::make_unique<Green>()); }
void Green::next(TrafficLight& light) { light.setState(std::make_unique<Red>()); }

}  // namespace zoo::app
