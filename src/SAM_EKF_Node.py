#!/usr/bin/env python3

import rospy
from geometry_msgs.msg import Pose2D, Pose, PoseWithCovarianceStamped, PoseWithCovariance
from sensor_msgs.msg import Imu
import tf2_geometry_msgs
from visualization_msgs.msg import Marker, MarkerArray

from EKFSLAM import *
import tf2_ros
from tf.transformations import quaternion_from_euler, euler_from_quaternion, quaternion_from_matrix
from tf.transformations import translation_matrix, quaternion_matrix

class EKFSLAMNode(object):
    # ---------------------------------------------------------------------
    # ---------------------- initialization -------------------------------
    # ---------------------------------------------------------------------

    def __init__(self):
        # motion model: 0 --> velocity based motion model, 1 --> constant velocity model,
        # 2 --> rpm model, 3 --> IMU model
        self.motionmodel = 1

        # initial pose of SAM
        # x0 = np.array([0.632, 0.0, -0.07])
        x0 = np.array([-0.032, -0.083, 0.349])

        # initialize EKF SLAM
        self.ekf = EKFSLAM(x0)

        # initialize publishers & subscribers
        self.subscribers = {}
        self.init_subscribers()

        self.publishers = {}
        self.init_publishers()

        # 3D acceleration of SAM
        self.acc = []

        # gyro data
        self.gyro = []

        # TODO: change timestep accordingly
        self.dt = 0.01

        # imu integrated velocity
        self.v_integrated = np.zeros(2)

        # last updated velocity and timestep
        self.pos_last = x0[0:2]
        self.t_last = rospy.get_time()
        self.theta_last = x0[2]

        self.last_meas = [0, 0, 0]

        # tfs
        self.tf_buffer = tf2_ros.Buffer(cache_time=rospy.Duration(200))
        self.listener = tf2_ros.TransformListener(self.tf_buffer)

        self.base_frame = rospy.get_param('/planner_node/base_frame_name','/poiu')
        self.docking_frame = rospy.get_param('/planner_node/docking_frame_name', '/uiop')

        print("Init cov: " + str(self.ekf.cov.diagonal()))

    def init_subscribers(self):
        self.subscribers["RelativePose"] = rospy.Subscriber("/docking_station/feature_model/estimated_pose",
                                                            PoseWithCovarianceStamped,
                                                            self.updateEKF)
        self.subscribers["imu"] = rospy.Subscriber("~/imu_data", Imu, self.process_imu)
        self.subscribers["control"] = rospy.Subscriber("~/odometry_data", Pose, self.predictEKF)

    def init_publishers(self):
        """ initialize ROS publishers and stores them in a dictionary"""
        # position of segway in world frame
        self.publishers["robot_pose"] = rospy.Publisher("~robot_pose", Pose2D, queue_size=1)
        self.publishers["SAM_PoseCov"] = rospy.Publisher("sam/EstimatedPose", PoseWithCovarianceStamped, queue_size=1)
        self.publishers["Station_PoseCov"] = rospy.Publisher("EstimatedStationPose", PoseWithCovarianceStamped, queue_size=1)
        self.publishers["station_pose"] = rospy.Publisher("~covariance", Pose2D, queue_size=1)

    def process_imu(self, msg):
        self.acc = np.array([msg.linear_acceleration.x,
                             msg.linear_acceleration.y,
                             msg.linear_acceleration.z])

        self.gyro = np.array([msg.angular_velocity.x,
                              msg.angular_velocity.y,
                              msg.angular_velocity.z])

        self.v_integrated += self.acc[0:2] * self.dt

    def predictEKF(self, controls):
        self.ekf.predict(controls, self.dt)
        self.publish_poses()

    def updateEKF(self, msg):
        print("I'm here!")
        # obtain velocity and angular velocity through numerical differentiation
        v = (self.ekf.x[0:2] - self.pos_last) / (rospy.get_time() - self.t_last)
        w = (self.ekf.x[2] - self.theta_last) / (rospy.get_time() - self.t_last)

        # update last values
        self.pos_last = self.ekf.x[0:2]
        self.theta_last = self.ekf.x[2]

        # predict EKF
        self.ekf.predict(v, w, rospy.get_time() - self.t_last)

        self.t_last = rospy.get_time()
        print("vel: " + str(v))
        print("w: " + str(w))

        # found_tf = False
        # while not found_tf:
        #     try:
        #         base_tfm_ds = self.tf_buffer.lookup_transform("sam/base_link", "docking_station_ned", rospy.Time(0))
        #         base_tfm_ned = self.tf_buffer.lookup_transform("sam/base_link_ned", "sam/base_link", rospy.Time(0))
        #         found_tf = True
        #     except (tf2_ros.ExtrapolationException):
        #         continue

        base_tfm_ds = self.tf_buffer.lookup_transform("sam/base_link", "docking_station_ned", rospy.Time(0))
        base_tfm_ned = self.tf_buffer.lookup_transform("sam/base_link_ned", "sam/base_link", rospy.Time(0))
        # meas_sam = self.tf_buffer.lookup_transform("sam/base_link", msg.header.frame_id, msg.header.stamp, rospy.Duration(0.00001))
        # ds_to_ned = self.tf_buffer.lookup_transform("docking_station_link", "docking_station_ned", rospy.Time.now(), rospy.Duration(0.00001))
        base_to_ds = PoseWithCovariance()
        base_to_ds.pose.position.x = base_tfm_ds.transform.translation.x
        base_to_ds.pose.position.y = base_tfm_ds.transform.translation.y
        base_to_ds.pose.position.z = base_tfm_ds.transform.translation.z
        base_to_ds.pose.orientation.x = base_tfm_ds.transform.rotation.x
        base_to_ds.pose.orientation.y = base_tfm_ds.transform.rotation.y
        base_to_ds.pose.orientation.z = base_tfm_ds.transform.rotation.z
        base_to_ds.pose.orientation.w = base_tfm_ds.transform.rotation.w
        meas_sam_transformed = tf2_geometry_msgs.do_transform_pose(base_to_ds, base_tfm_ned)
        # meas_sam_transformed_ = tf2_geometry_msgs.do_transform_pose(msg.pose, ds_to_ned)
        # meas_sam_transformed = tf2_geometry_msgs.do_transform_pose(meas_sam_transformed_,
                                                                   # meas_sam)

        qw = meas_sam_transformed.pose.orientation.w
        qx = meas_sam_transformed.pose.orientation.x
        qy = meas_sam_transformed.pose.orientation.y
        qz = meas_sam_transformed.pose.orientation.z
        # qw = meas_sam_transformed.transform.rotation.w
        # qx = meas_sam_transformed.transform.rotation.x
        # qy = meas_sam_transformed.transform.rotation.y
        # qz = meas_sam_transformed.transform.rotation.z
        rpy = euler_from_quaternion([qx, qy, qz, qw])

        meas = np.array([meas_sam_transformed.pose.position.x,
                         meas_sam_transformed.pose.position.y,
                         rpy[2]])
        # meas = np.array([meas_sam_transformed.transform.translation.x,
                         # meas_sam_transformed.transform.translation.y,
                         # rpy[2]])
        print(meas)
        print(self.ekf.cov.diagonal())
        self.ekf.update(meas)
        self.publish_poses()
        self.last_meas = meas

    def publish_poses(self):
        SAM_pose = Pose2D()
        SAM_pose.x = self.ekf.x[0]
        SAM_pose.y = self.ekf.x[1]
        SAM_pose.theta = self.ekf.x[2]

        self.publishers["robot_pose"].publish(SAM_pose)

        landmark_pose = Pose2D()
        landmark_pose.x = self.ekf.x[3]
        landmark_pose.y = self.ekf.x[4]
        landmark_pose.theta = 0.0

        self.publishers["station_pose"].publish(landmark_pose)


        # FOR DEBUGGING
        # Publish pose with covariance
        pose3D = PoseWithCovarianceStamped()
        pose3D.header.stamp = rospy.Time.now()
        pose3D.header.frame_id = "world_ned"
        pose3D.pose.pose.position.x = self.ekf.x[0]
        pose3D.pose.pose.position.y = self.ekf.x[1]
        pose3D.pose.pose.position.z = -1.

        quat = quaternion_from_euler(0., 0., self.ekf.x[2])
        pose3D.pose.pose.orientation.x = quat[0]
        pose3D.pose.pose.orientation.y = quat[1]
        pose3D.pose.pose.orientation.z = quat[2]
        pose3D.pose.pose.orientation.w = quat[3]

        pose3D.pose.covariance = [self.ekf.cov[0, 0], self.ekf.cov[0, 1], 0., 0., 0., self.ekf.cov[0, 2]] +\
                            [self.ekf.cov[1, 0], self.ekf.cov[1, 1], 0., 0., 0., self.ekf.cov[1, 2]] + \
                            [0., 0., 0., 0., 0., 0.] +\
                            [0., 0., 0., 0., 0., 0.] + \
                            [0., 0., 0., 0., 0., 0.] + \
                            [self.ekf.cov[2, 0], self.ekf.cov[2, 1], 0., 0., 0., self.ekf.cov[2, 2]]

        self.publishers["SAM_PoseCov"].publish(pose3D)

        lm3D = PoseWithCovarianceStamped()
        lm3D.header.stamp = rospy.Time.now()
        lm3D.header.frame_id = "world_ned"
        lm3D.pose.pose.position.x = self.ekf.x[3]
        lm3D.pose.pose.position.y = self.ekf.x[4]
        lm3D.pose.pose.position.z = -1.

        quat = quaternion_from_euler(0., 0., self.ekf.x[5])
        lm3D.pose.pose.orientation.x = quat[0]
        lm3D.pose.pose.orientation.y = quat[1]
        lm3D.pose.pose.orientation.z = quat[2]
        lm3D.pose.pose.orientation.w = quat[3]

        lm3D.pose.covariance = [self.ekf.cov[3, 3], self.ekf.cov[3, 4], 0., 0., 0., self.ekf.cov[3, 5]] + \
                                 [self.ekf.cov[4, 3], self.ekf.cov[4, 4], 0., 0., 0., self.ekf.cov[4, 5]] + \
                                 [0., 0., 0., 0., 0., 0.] + \
                                 [0., 0., 0., 0., 0., 0.] + \
                                 [0., 0., 0., 0., 0., 0.] + \
                                 [self.ekf.cov[5, 3], self.ekf.cov[5, 4], 0., 0., 0., self.ekf.cov[5, 5]]

        self.publishers["Station_PoseCov"].publish(lm3D)

        # Visualize measurement with respect to sam frame
        marker = Marker()

        marker.header.frame_id = "/map"
        marker.header.stamp = rospy.Time.now()

        # set shape, Arrow: 0; Cube: 1 ; Sphere: 2 ; Cylinder: 3
        marker.type = 2
        marker.id = 0

        # Set the scale of the marker
        marker.scale.x = 1.0
        marker.scale.y = 1.0
        marker.scale.z = 1.0

        # Set the color
        marker.color.r = 0.0
        marker.color.g = 1.0
        marker.color.b = 0.0
        marker.color.a = 1.0

        # Set the pose of the marker
        marker.pose.position.x = 0
        marker.pose.position.y = 0
        marker.pose.position.z = 0
        marker.pose.orientation.x = 0.0
        marker.pose.orientation.y = 0.0
        marker.pose.orientation.z = 0.0
        marker.pose.orientation.w = 1.0


def main():
    """Starts the EKF SLAM Node"""
    rospy.init_node("EKF_Node")
    EKFSLAMNode()
    rospy.spin()


if __name__ == "__main__":
    main()





