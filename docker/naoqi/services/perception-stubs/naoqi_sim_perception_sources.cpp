// _NaoqiSimPerceptionSources: loads the suite's shared people-perception sources into ALModularity.
//
// Leaving the built-in people-perception library out of NAOqi's boot (specs/services/
// people-perception.md) also leaves out the modularity program it loads first,
// peopleperception_sources.mds: the segmentation settings (Labeling_*) and defaults that other
// vision processes read. 2.8's fast person tracking and find person head processes need them,
// and ALBasicAwareness needs those processes to track a person (specs/services/perception-stubs.md).
// This module is an autoload entry right after modularityperception, which registers ALModularity:
// its init() loads the programs there, synchronously, before the tracking libraries load.
//
//   NAOQI_SIM_MODULARITY_PROGRAMS  the .mds files to load, in order
//
// One source for NAOqi 2.1 and 2.8 (2.1's entrypoint does not list it: its tracking programs load
// on their own), compiled in the image build (Dockerfile stage `native`).
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <sstream>
#include <string>

#include <alcommon/albroker.h>
#include <alcommon/albrokermanager.h>
#include <alcommon/almodule.h>
#include <alcommon/alproxy.h>
#include <boost/shared_ptr.hpp>

#ifndef ALCALL
#define ALCALL __attribute__((visibility("default")))
#endif

class NaoqiSimPerceptionSources : public AL::ALModule {
 public:
  NaoqiSimPerceptionSources(boost::shared_ptr<AL::ALBroker> broker, const std::string& name)
      : AL::ALModule(broker, name) {
    setModuleDescription("naoqi-sim: loads the shared people-perception sources into ALModularity");
  }

  // Failures are logged, not thrown: the entrypoint checks the tracking modules answer.
  void init() {
    const char* value = std::getenv("NAOQI_SIM_MODULARITY_PROGRAMS");
    std::istringstream programs(value ? value : "");
    std::string program;
    try {
      AL::ALProxy modularity(getParentBroker(), "ALModularity");
      while (programs >> program) {
        std::fprintf(stderr, "[naoqi_sim_perception_sources] loading %s\n", program.c_str());
        modularity.callVoid("loadProgramFromFile", program);
      }
    } catch (const std::exception& e) {
      std::fprintf(stderr, "[naoqi_sim_perception_sources] failed on %s: %s\n", program.c_str(), e.what());
    }
  }
};

extern "C" {
ALCALL int _createModule(boost::shared_ptr<AL::ALBroker> broker) {
  AL::ALBrokerManager::setInstance(broker->fBrokerManager.lock());
  AL::ALBrokerManager::getInstance()->addBroker(broker);
  AL::ALModule::createModule<NaoqiSimPerceptionSources>(broker, "_NaoqiSimPerceptionSources");
  return 0;
}
ALCALL int _closeModule() { return 0; }
}
